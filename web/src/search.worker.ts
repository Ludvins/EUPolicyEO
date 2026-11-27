import { Release } from "./assets";
import { projectEmbeddings } from "./projection";
import { bm25, evidenceForms, hybridRank, rank, supportedRows, withTopicEvidence } from "./ranking";
import type { Corpus, EmbeddingPoint, SearchTask } from "./types";
import type { Encoder } from "./dense";

const corpora: Corpus[] = ["eo", "projects"];
let current: Promise<Release> | undefined;
let encoder: Encoder | undefined;
const documents = new Map<Corpus, Awaited<ReturnType<Release["corpus"]>>>();
const vectors = new Map<Corpus, DataView>();
const forms = new Map<Corpus, Map<string, string[]>>();
let activeId: string | undefined;
let pending = Promise.resolve();

async function search(task: SearchTask & { id: number; releaseId: string; parity?: boolean; project?: boolean }) {
  const start = performance.now();
  const release = await (current ??= Release.open());
  if (release.manifest.release_id !== task.releaseId || (activeId && activeId !== task.releaseId)) {
    throw new Error("Active release changed. Reload to continue.");
  }
  activeId = task.releaseId;
  if (task.profile?.query === null) {
    return { id: task.id, mode: task.mode, eo: [], projects: [], elapsedMs: performance.now() - start, encodeMs: 0 };
  }
  const query = task.profile?.query ?? task.query;
  const usesEmbeddings = task.mode === "dense" || task.mode === "hybrid";
  const needEncoder = usesEmbeddings && !encoder;
  if (usesEmbeddings && (!__DENSE_ENABLED__ || !release.manifest.dense)) {
    throw new Error("Model-assisted search is unavailable for this build.");
  }
  const dense = __DENSE_ENABLED__ && usesEmbeddings ? await import("./dense") : undefined;
  if (needEncoder && dense) encoder = await dense.Encoder.load(release);
  const encodedAt = performance.now();
  const vector = usesEmbeddings ? await encoder!.query(query) : undefined;
  const encodeMs = performance.now() - encodedAt;
  const results = await Promise.all(corpora.map(async corpus => {
    if (!documents.has(corpus)) documents.set(corpus, await release.corpus(corpus));
    const {docs, index} = documents.get(corpus)!;
    let eligible: number[] | undefined;
    if (!task.profile && release.manifest.free_text_policy) {
      if (!forms.has(corpus)) forms.set(corpus, evidenceForms(index));
      eligible = supportedRows(index, forms.get(corpus)!, query, release.manifest.free_text_policy);
      if (!eligible.length) return [];
    }
    const scope = (scores: Map<number, number>) => {
      if (task.profile) return withTopicEvidence(docs, scores, task.profile);
      if (eligible) return new Map(eligible.map(i => [i, scores.get(i) ?? 0]));
      return scores;
    };
    const lexical = task.mode === "dense" ? undefined : scope(bm25(index, query));
    if (dense && vector) {
      if (!vectors.has(corpus)) {
        const [ids, matrix] = await Promise.all([
          release.json<string[]>(`vectors/${corpus}.ids.json`),
          release.binary(`vectors/${corpus}.f32`),
        ]);
        if (ids.length !== docs.length || ids.some((id, i) => id !== docs[i].id)) throw new Error("Dense document ID mismatch");
        vectors.set(corpus, new DataView(matrix));
      }
      const semantic = scope(dense.cosineVectors(vectors.get(corpus)!, vector, docs.length));
      if (lexical) return hybridRank(docs, lexical, semantic, task.constraints, task.profile);
      return rank(docs, semantic, task.constraints, 10, task.profile);
    }
    return rank(docs, lexical!, task.constraints, 10, task.profile);
  }));
  let projection: EmbeddingPoint[] | undefined;
  if (task.project && vector && results.some(group => group.length)) {
    const names: { id: string | null; group: EmbeddingPoint["group"] }[] = [{id: null, group: "query"}];
    const samples = [vector];
    for (const [i, corpus] of corpora.entries()) {
      const docs = documents.get(corpus)!.docs;
      const matrix = vectors.get(corpus)!;
      const indices = new Map(docs.map((doc, row) => [doc.id, row]));
      for (const { doc } of results[i]) {
        const offset = indices.get(doc.id)! * vector.length * 4;
        samples.push(Float32Array.from({ length: vector.length }, (_, col) => matrix.getFloat32(offset + col * 4, true)));
        names.push({ id: doc.id, group: corpus });
      }
    }
    projection = projectEmbeddings(samples).map(([x, y], i) => ({ ...names[i], x, y }));
  }
  return { id: task.id, mode: task.mode, eo: results[0], projects: results[1], projection, elapsedMs: performance.now() - start,
    encodeMs, vector: task.parity && vector ? Array.from(vector) : undefined };
}

self.addEventListener("message", ({data}) => {
  pending = pending.then(async () => {
    try {
      self.postMessage(await search(data));
    } catch (error) {
      if (!activeId) current = undefined;
      self.postMessage({ id: data.id, error: error instanceof Error ? error.message : "Search failed" });
    }
  });
});
