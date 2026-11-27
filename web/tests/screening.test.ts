import { expect, it } from "vitest";
import { assessCollections } from "../src/screening";
import type { Result } from "../src/types";

const result: Result = {
  doc: {
    id: "cdse:example", title: "Tree cover", description: null, provider: "CDSE",
    metadata_quality_flags: [], spatial_resolution_m: 10,
    bbox_parts: [[170, -20, 180, 20], [-180, -20, -170, 20]],
    intervals: [{ start: "2020-01-01T00:00:00Z", end: null, ongoing: true }],
    provenance: { source: "cdse", source_id: "example", source_url: "https://stac.dataspace.copernicus.eu", snapshot_id: "s" },
  },
  score: 0,
  compatibility: "not_requested",
  evidence_use: {
    role: "direct_measurement", note: "Measures percentage tree crown cover.",
    source_url: "https://land.copernicus.eu",
  },
};

it("uses the configured threshold and never treats a retrieval score as evidence", () => {
  const undocumented = { ...result, score: 99, evidence_use: undefined };
  const [documented, unknown] = assessCollections([result, undocumented], { allowContext: false, maxResolution: 10 });
  expect(documented.overall).toBe("meets");
  expect(documented.checks.map(check => check.status)).toEqual(["meets", "meets"]);
  expect(unknown.overall).toBe("unknown");
  expect(assessCollections([result], { allowContext: false, maxResolution: 9 })[0].overall).toBe("fails");
  expect(() => assessCollections([result], { allowContext: false, maxResolution: 0 })).toThrow(/greater than zero/);
});

it("distinguishes a supporting role from direct measurement and missing resolution", () => {
  const context: Result = {
    ...result,
    doc: { ...result.doc, spatial_resolution_m: null },
    evidence_use: { ...result.evidence_use!, role: "supporting_context" },
  };
  expect(assessCollections([context], { allowContext: false })[0].overall).toBe("partial");
  expect(assessCollections([context], { allowContext: true })[0].overall).toBe("meets");
  expect(assessCollections([context], { allowContext: true, maxResolution: 20 })[0].overall).toBe("unknown");
});

it("screens the assessment area and dates independently from the search filters", () => {
  const [overlap] = assessCollections([result], {
    allowContext: false, bbox: [175, -3, -175, 3], start: "2021-01-01T00:00:00Z",
  });
  expect(overlap.checks.map(check => check.status)).toEqual(["meets", "partial", "partial"]);
  const [excluded] = assessCollections([result], {
    allowContext: false, bbox: [0, 0, 3, 3], end: "2019-12-31T23:59:59.999Z",
  });
  expect(excluded.checks.map(check => check.status)).toEqual(["meets", "fails", "fails"]);
  expect(excluded.overall).toBe("fails");
  const worldwide: Result = { ...result, doc: { ...result.doc, bbox_parts: [[-180, -90, 180, 90]] } };
  expect(assessCollections([worldwide], { allowContext: false, bbox: [0, 0, 3, 3] })[0].overall).toBe("unknown");
});

it("requires a dated endpoint before treating an ongoing interval as overlapping", () => {
  const undated: Result = {
    ...result, doc: { ...result.doc, intervals: [{ start: null, end: null, ongoing: true }] },
  };
  const [assessment] = assessCollections([undated], { allowContext: false, start: "2021-01-01T00:00:00Z" });
  expect(assessment.checks[1].status).toBe("unknown");
});

it("uses verified catalogue findings only for the documented collection and provision", () => {
  const glance: Result = {
    ...result, score: 0, evidence_use: undefined,
    doc: {
      ...result.doc, id: "cmr:C2763264675-LPCLOUD", spatial_resolution_m: null,
      intervals: [{ start: "2001-07-01T00:00:00Z", end: "2021-07-01T23:59:59Z", ongoing: false }],
    },
  };
  const [habitat] = assessCollections([glance], { allowContext: false, maxResolution: 20 }, "h");
  expect(habitat.checks.map(check => check.status)).toEqual(["partial", "fails"]);
  expect(habitat.checks[1].sourceUrl).toContain("GLanCE30.001");
  expect(assessCollections([glance], { allowContext: true }, "h")[0].overall).toBe("meets");
  expect(assessCollections([glance], { allowContext: true }, "d")[0].overall).toBe("unknown");
  const [laterPeriod] = assessCollections([glance], { allowContext: false, start: "2020-01-01T00:00:00Z" }, "h");
  expect(laterPeriod.checks[1].status).toBe("unknown");
  expect(laterPeriod.checks[1].detail).toContain("after the European series");

  const campground = { ...glance, doc: { ...glance.doc, id: "cmr:C2232411685-CEOS_EXTRA" } };
  const [excluded] = assessCollections([campground], { allowContext: true }, "h");
  expect(excluded.overall).toBe("fails");
  expect(excluded.checks[0].sourceUrl).toBe("https://pubs.usgs.gov/of/2004/1073/");
});
