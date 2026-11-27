import type { BBox, Compatibility, Constraints, Document, LexicalIndex, Result, RetrievalProfile } from "./types";

const STOP = new Set("a an and are as at be by for from in is it of on or that the to was were with".split(" "));
const STRICT_FREE_TEXT_POLICY = "lexical-evidence-v1";
export const FREE_TEXT_POLICY = "lexical-evidence-v2";
export const FREE_TEXT_POLICIES = [STRICT_FREE_TEXT_POLICY, FREE_TEXT_POLICY] as const;
export type FreeTextPolicy = typeof FREE_TEXT_POLICIES[number];
const QUERY_FILLER = new Set((
  "can could dataset datasets find give information looking map maps mapping measure measures " +
  "measurement measurements measuring method methods monitor monitoring observations observe " +
  "please product products project projects records repeated research search show studies study " +
  "using want which will would"
).split(" "));

export function tokenize(text: string): string[] {
  return (text.normalize("NFKC").toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []).filter(t => !STOP.has(t));
}

function evidenceTerm(token: string) {
  if (token === "european") return "europe";
  if (Array.from(token).length >= 5 && token !== "species" && token !== "series") {
    if (token.endsWith("ies")) return token.slice(0, -3) + "y";
    if (/(ches|shes|xes|sses|zzes)$/.test(token)) return token.slice(0, -2);
    if (token.endsWith("s") && !/(ss|us|is)$/.test(token)) return token.slice(0, -1);
  }
  return token;
}

export function evidenceForms(index: LexicalIndex) {
  const forms = new Map<string, string[]>();
  for (const term of Object.keys(index.postings)) {
    const key = evidenceTerm(term);
    if (!forms.has(key)) forms.set(key, []);
    forms.get(key)!.push(term);
  }
  return forms;
}

export function supportedRows(index: LexicalIndex, forms: Map<string, string[]>, query: string,
  policy: FreeTextPolicy = FREE_TEXT_POLICY) {
  const tokens = tokenize(query);
  const anchors = tokens.filter(term => !QUERY_FILLER.has(term));
  const selected = anchors.length ? anchors : tokens;
  const ordered = (policy === FREE_TEXT_POLICY
    ? selected.filter(term => !["s", "use", "testing"].includes(term))
    : selected).map(evidenceTerm);
  const targets = new Set(ordered);
  const matches = new Map<string, Set<number>>();
  const counts = new Map<number, number>();
  for (const term of targets) {
    const rows = new Set<number>();
    for (const spelling of forms.get(term) ?? []) {
      for (const [row] of index.postings[spelling]) rows.add(row);
    }
    matches.set(term, rows);
    for (const row of rows) counts.set(row, (counts.get(row) ?? 0) + 1);
  }
  const minimum = Math.min(2, targets.size);
  if (policy === FREE_TEXT_POLICY) {
    if (targets.size <= 4) return [...counts.keys()].filter(row => counts.get(row)! >= minimum);
    const adjacent = new Set<number>();
    for (let i = 1; i < ordered.length; i++) {
      if (ordered[i-1] === ordered[i]) continue;
      const left = matches.get(ordered[i-1])!, right = matches.get(ordered[i])!;
      for (const row of left) if (right.has(row)) adjacent.add(row);
    }
    return [...counts.keys()].filter(row => counts.get(row)! >= 3 || adjacent.has(row));
  }

  const support = new Map<number, number>();
  let totalWeight = 0;
  for (const rows of matches.values()) {
    const weight = Math.min(3, 1 + Math.log1p(index.lengths.length / (rows.size + 1)));
    totalWeight += weight;
    for (const row of rows) {
      support.set(row, (support.get(row) ?? 0) + weight);
    }
  }
  const eligible = [...counts.keys()].filter(row =>
    counts.get(row)! >= minimum && support.get(row)! >= 0.5 * totalWeight);
  return eligible;
}

export function bm25(index: LexicalIndex, query: string): Map<number, number> {
  const terms = new Map<string, number>();
  const scores = new Map<number, number>();
  for (const term of tokenize(query)) terms.set(term, (terms.get(term) ?? 0) + 1);
  const { k1, b, lengths } = index;
  for (const [term, count] of terms) {
    if (!Object.hasOwn(index.postings, term)) continue;
    const rows = index.postings[term];
    const idf = Math.log1p((lengths.length - rows.length + 0.5) / (rows.length + 0.5));
    for (const [i, freq] of rows) {
      const denom = freq + k1 * (1 - b + b * lengths[i] / (index.average || 1));
      scores.set(i, (scores.get(i) ?? 0) + count * idf * freq * (k1 + 1) / denom);
    }
  }
  return scores;
}

export function withTopicEvidence(docs: Document[], scores: Map<number, number>, profile: RetrievalProfile) {
  const phrase = (text: string) => " " + tokenize(text).join(" ") + " ";
  const groups = profile.evidence_groups.map(group => group.map(phrase));
  const eligible = new Map<number, number>();
  const verified = profile.record_evidence ?? {};
  if (profile.record_evidence) {
    docs.forEach((doc, i) => {
      if (Object.hasOwn(verified, doc.id)) eligible.set(i, scores.get(i) ?? 0);
    });
  }
  for (const [index, score] of scores) {
    if (eligible.has(index)) continue;
    const doc = docs[index];
    const fields = [doc.title, doc.description, ...(doc.keywords ?? [])]
      .filter((field): field is string => !!field)
      .map(phrase);
    if (groups.every(group => group.some(term => fields.some(field => field.includes(term))))) {
      eligible.set(index, score);
    }
  }
  return eligible;
}

export function splitBox(box: BBox): BBox[] {
  const [w, s, e, n] = box;
  if (!box.every(Number.isFinite) || w < -180 || w > 180 || e < -180 || e > 180 ||
      s < -90 || n > 90 || s > n) throw new Error("Enter a valid west, south, east, north bounding box");
  return w <= e ? [box] : [[w, s, 180, n], [-180, s, e, n]];
}

function overlaps(a: BBox, b: BBox) {
  return a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1];
}

function timeOverlap(value: NonNullable<Document["intervals"]>[number], query: Constraints) {
  const start = query.start ? Date.parse(query.start) : null;
  const end = query.end ? Date.parse(query.end) : null;
  const lower = value.start ? Date.parse(value.start) : null;
  const upper = value.end ? Date.parse(value.end) : null;
  if ((end !== null && lower !== null && lower > end) ||
      (start !== null && upper !== null && upper < start)) return false;
  if ((end !== null && lower === null) || (start !== null && upper === null && value.ongoing !== true)) {
    if (lower !== null && start !== null && start <= lower && (end === null || lower <= end)) return true;
    if (upper !== null && end !== null && upper <= end && (start === null || start <= upper)) return true;
    return null;
  }
  return true;
}

export function compatibility(doc: Document, query: Constraints): Compatibility {
  const checks: (boolean | null)[] = [];
  if (query.bbox) {
    const boxes = splitBox(query.bbox);
    checks.push(doc.bbox_parts?.length ? doc.bbox_parts.some(a => boxes.some(b => overlaps(a, b))) : null);
  }
  if (query.start || query.end) {
    const times = (doc.intervals ?? []).map(value => timeOverlap(value, query));
    checks.push(times.includes(true) ? true : !times.length || times.includes(null) ? null : false);
  }
  return !checks.length ? "not_requested" :
    checks.includes(false) ? "incompatible" : checks.includes(null) ? "unknown" : "compatible";
}

export function rank(docs: Document[], scores: Map<number, number>, constraints: Constraints, top = 10,
  profile?: RetrievalProfile | null): Result[] {
  const out: Result[] = [];
  const evidence = profile?.record_evidence ?? {};
  const priority = (i: number) => {
    const role = evidence[docs[i].id]?.role;
    return role === "supporting_context" ? 1 : role ? 2 : 0;
  };
  const cmp = (a: number, b: number) => (priority(b) - priority(a)) || (scores.get(b)! - scores.get(a)!) ||
    (docs[a].id < docs[b].id ? -1 : docs[a].id > docs[b].id ? 1 : 0);
  for (const i of [...scores.keys()].sort(cmp)) {
    const doc = docs[i];
    const match = doc.provenance.source === "cordis" ? "not_requested" : compatibility(doc, constraints);
    if (constraints.strict_metadata && match === "incompatible") continue;
    out.push({ doc, score: scores.get(i)!, compatibility: match, evidence_use: evidence[doc.id] });
    if (out.length === top) break;
  }
  return out;
}

export function hybridRank(docs: Document[], lexical: Map<number, number>, semantic: Map<number, number>,
  constraints: Constraints, profile?: RetrievalProfile | null): Result[] {
  const poolSize = 60;
  const rankConstant = 60;
  const exactMatches = new Map([...lexical].filter(([, score]) => score > 0));
  const positions = new Map(docs.map((doc, i) => [doc.id, i]));
  const combined = new Map<number, number>();
  for (const scores of [exactMatches, semantic]) {
    for (const [position, {doc}] of rank(docs, scores, constraints, poolSize, profile).entries()) {
      const row = positions.get(doc.id)!;
      combined.set(row, (combined.get(row) ?? 0) + 1 / (rankConstant + position + 1));
    }
  }
  return rank(docs, combined, constraints, 10, profile);
}
