import type { Mode } from "./types";

export const searchModes = {
  bm25: {
    label: "Keyword search",
    scoreLabel: "BM25 score",
    note: "Measures keyword matches in the indexed fields.",
  },
  dense: {
    label: "Semantic search",
    scoreLabel: "Similarity score",
    note: "Measures similarity between the query and the indexed record text.",
  },
  hybrid: {
    label: "Hybrid search",
    scoreLabel: "Hybrid score",
    note: "Combines the positions of a record in keyword and semantic search.",
  },
} satisfies Record<Mode, {label: string; scoreLabel: string; note: string}>;

export function formatScore(score: number, mode: Mode) {
  return Number.isFinite(score) ? score.toFixed(mode === "hybrid" ? 4 : 3) : "Unavailable";
}
