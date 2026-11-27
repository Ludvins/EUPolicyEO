import { expect, it } from "vitest";
import { bm25, compatibility, evidenceForms, hybridRank, rank, supportedRows, tokenize, withTopicEvidence } from "../src/ranking";
import { fitBounds } from "../src/bbox-map";
import { projectEmbeddings } from "../src/projection";
import type { Document, LexicalIndex, RetrievalProfile } from "../src/types";

const doc: Document = { id: "cdse:one", title: "Forest", description: null,
  provider: "CDSE", metadata_quality_flags: [], bbox_parts: [[170, -20, 180, 20], [-180, -20, -170, 20]],
  provenance: { source: "cdse", source_id: "one", source_url: "https://stac.dataspace.copernicus.eu", snapshot_id: "s" } };

it("normalizes Unicode, legal identifiers, decimal and date separators", () => {
  expect(tokenize("CAFÉ ſentinel_2 Regulation (EU) 2024/1991 3.14")).toEqual(
    ["café", "sentinel", "2", "regulation", "eu", "2024", "1991", "3", "14"]);
});

it("checks distinct query evidence and normalizes simple word forms", () => {
  const idx: LexicalIndex = {tokenizer: "nfkc-lower-unicode-alnum-v1", ids: ["a", "b"],
    lengths: [3, 2], average: 2.5, k1: 1.2, b: 0.75,
    postings: {acoustic: [[0, 1]], bird: [[0, 1]], europe: [[0, 1]],
      concentration: [[1, 1]], oxygen: [[1, 1]]}};
  const forms = evidenceForms(idx);
  expect(supportedRows(idx, forms, "Find acoustic studies of European birds")).toEqual([0]);
  expect(supportedRows(idx, forms, "oxygen concentration on a remote natural satellite")).toEqual([1]);
  expect(supportedRows(idx, forms, "oxygen measurements of remote natural satellite concentrations")).toEqual([]);
  expect(supportedRows(idx, forms, "oxygen concentration on a remote natural satellite", "lexical-evidence-v1")).toEqual([]);
  expect(supportedRows(idx, forms, "BIRDS")).toEqual([0]);
});
it("preserves unknowns and antimeridian extent", () => {
  expect(compatibility(doc, {bbox: [175, -1, -175, 1]})).toBe("compatible");
  expect(compatibility(doc, {start: "2025-01-01T00:00:00Z"})).toBe("unknown");
  expect(compatibility(doc, {bbox: [0, 0, 2, 2]})).toBe("incompatible");
});
it("uses stable IDs for exact ties and no score for unmatched terms", () => {
  const idx: LexicalIndex = {tokenizer: "nfkc-lower-unicode-alnum-v1", ids: ["z", "a"],
    lengths: [1, 1], average: 1, k1: 1.2, b: 0.75, postings: {tree: [[0, 1], [1, 1]]}};
  expect(bm25(idx, "absent").size).toBe(0);
  expect(rank([{...doc, id: "z"}, {...doc, id: "a"}], bm25(idx, "tree"), {}).map(r => r.doc.id)).toEqual(["a", "z"]);
});

it("combines positive keyword and semantic ranks after filtering incompatible records", () => {
  const docs = ["a", "b", "c", "outside"].map(id => ({...doc, id}));
  docs[3].bbox_parts = [[0, 0, 1, 1]];
  const lexical = new Map([[0, 20], [1, 10], [2, 0], [3, 50]]);
  const semantic = new Map([[0, 0.5], [1, 0.9], [2, 0.6], [3, 1.0]]);
  const results = hybridRank(docs, lexical, semantic, {bbox: [175, -1, -175, 1], strict_metadata: true});
  expect(results.map(result => result.doc.id)).toEqual(["b", "a", "c"]);
  expect(results[0].score).toBeCloseTo(1 / 61 + 1 / 62);
  expect(results[2].score).toBeCloseTo(1 / 62);
});

it("places source-documented evidence above metadata matches while preserving scores and filters", () => {
  const measurements = {...doc, id: "cdse:measurement", title: "Crown density"};
  const context = {...doc, id: "cdse:context", title: "Tree cover map"};
  const matches = {...doc, id: "cdse:matches", title: "Tree cover year"};
  const docs = [measurements, context, matches];
  const profile: RetrievalProfile = {query: "tree cover", evidence_groups: [["tree cover"]],
    record_evidence: {
      [measurements.id]: {role: "direct_measurement", note: "Crown coverage", source_url: "https://land.copernicus.eu"},
      [context.id]: {role: "supporting_context", note: "Land cover", source_url: "https://land.copernicus.eu"},
    }};
  const eligible = withTopicEvidence(docs, new Map([[1, 7], [2, 12]]), profile);
  expect(rank(docs, eligible, {}, 10, profile).map(r => [r.doc.id, r.score])).toEqual([
    [measurements.id, 0], [context.id, 7], [matches.id, 12],
  ]);
  expect(rank(docs, eligible, {bbox: [0, 0, 2, 2], strict_metadata: true}, 10, profile)).toEqual([]);
});

it("requires a title or measured variable for unreviewed habitat collections", () => {
  const collections = [
    { ...doc, id: "cmr:tags", title: "National water survey", keywords: ["Aquatic ecosystems", "Water quality"] },
    { ...doc, id: "cdse:variable", title: "Wetland observations", measurement_terms: ["Vegetation condition"] },
    { ...doc, id: "cmr:documented", title: "Vegetation index" },
  ];
  const scores = new Map([[0, 9], [1, 4], [2, 2]]);
  const profile: RetrievalProfile = { query: "habitat condition", evidence_groups: [
    ["ecosystems", "wetland"], ["quality", "condition"],
  ], record_evidence: {
    "cmr:documented": { role: "supporting_context", note: "Vegetation context", source_url: "https://cmr.earthdata.nasa.gov/" },
  } };
  expect([...withTopicEvidence(collections, scores, profile).keys()]).toEqual([2, 0]);
  expect([...withTopicEvidence(collections, scores, profile, true).keys()]).toEqual([2, 1]);
});

it("fits small areas and uses a wrapped regional view for meridian crossings", () => {
  const box = fitBounds([-7.5, 36, -1.5, 38.8]);
  expect(box[0]).toBeLessThan(-7.5);
  expect(box[2]).toBeGreaterThan(-1.5);
  expect(box[3]).toBeGreaterThan(38.8);
  const wrapped = fitBounds([175, -25, -170, 25]);
  expect(wrapped[0]).toBeLessThan(-185);
  expect(wrapped[2]).toBeGreaterThan(-170);
  expect(wrapped[2] - wrapped[0]).toBeLessThan(180);
});

it("projects planar embeddings without changing pairwise distances", () => {
  const input = [[1, 1, 5], [2, 6, 5], [6, 1, 5], [2, 1, 5]];
  const points = projectEmbeddings(input);
  expect(points).toHaveLength(input.length);
  for (const [i, a] of points.entries()) {
    for (const [j, b] of points.entries()) {
      const distance = Math.hypot(input[i][0] - input[j][0], input[i][1] - input[j][1]);
      expect(Math.hypot(a[0] - b[0], a[1] - b[1])).toBeCloseTo(distance, 9);
    }
  }
  expect(projectEmbeddings([[1, 2], [1, 2]])).toEqual([[0, 0], [0, 0]]);
});
