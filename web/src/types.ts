export type Corpus = "eo" | "projects";
export type Ranker = "bm25" | "dense";
export type Mode = Ranker | "hybrid";
export type BBox = [number, number, number, number];
export type Compatibility = "compatible" | "incompatible" | "unknown" | "not_requested";

export interface Constraints {
  bbox?: BBox;
  start?: string;
  end?: string;
  strict_metadata?: boolean;
}
export interface Document {
  id: string;
  title: string;
  description: string | null;
  provider: string | null;
  metadata_quality_flags: string[];
  provenance: {
    source: string; source_id: string; source_url: string; snapshot_id: string;
    retrieved_at?: string; revision?: string | null; raw_sha256?: string;
  };
  bbox_parts?: BBox[] | null;
  intervals?: { start: string | null; end: string | null; ongoing: boolean | null }[];
  temporal_start?: string | null;
  temporal_end?: string | null;
  ongoing?: boolean | null;
  spatial_resolution_m?: number | null;
  platform?: string[];
  instrument?: string[];
  processing_level?: string | null;
  keywords?: string[];
  discovery_terms?: string[];
  measurement_terms?: string[];
  topics?: string[];
  programme?: string | null;
  acronym?: string | null;
  start_date?: string | null;
  end_date?: string | null;
}
export interface LexicalIndex {
  tokenizer: string;
  k1: number;
  b: number;
  ids: string[];
  lengths: number[];
  average: number;
  postings: Record<string, [number, number][]>;
}
export interface Section {
  celex: string; article: string; paragraph: string | null; point: string | null; text: string;
  provenance: { source_url: string };
}
export interface EvidenceUse {
  role: "direct_measurement" | "research_method" | "supporting_context";
  note: string;
  source_url: string;
}
export interface RetrievalProfile {
  query: string | null;
  evidence_groups: string[][];
  record_evidence?: Record<string, EvidenceUse>;
}
export interface Evidence {
  requirement: {
    id: string; observable: string; query: string; verbatim_evidence: string;
    parent_evidence: string | null; review_status: string; modality: string;
    search_profile?: RetrievalProfile | null;
  };
  section: Section;
  parent_section: Section | null;
}
export interface Manifest {
  schema_version: 1; release_id: string; created_at: string;
  registry_version: string; parent_ranker: string; parent_snapshot_id: string;
  parent_build_id: string; public_corpus_hash: string; git_revision: string | null;
  subset_policy: string; counts: Record<Corpus, number>; source_counts: Record<string, number>;
  source_freshness: Record<string, { latest: string; mode: string; pages: number; bounds: string[] }>;
  rankers: Ranker[]; tokenizer: string; assets: Record<string, { bytes: number; sha256: string }>;
  free_text_policy?: "lexical-evidence-v1" | "lexical-evidence-v2";
  dense: {
    dimension: number; max_tokens: number; revision: string; encoder: string;
    parity_gates: { min_cosine: number; mean_top10_overlap: number };
  } | null;
}
export interface Result { doc: Document; score: number; compatibility: Compatibility; evidence_use?: EvidenceUse }
export interface EmbeddingPoint {
  id: string | null;
  group: "query" | Corpus;
  x: number;
  y: number;
}
export interface SearchTask {
  query: string; constraints: Constraints; mode: Mode;
  profile?: RetrievalProfile | null;
}
