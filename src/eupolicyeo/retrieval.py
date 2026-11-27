import math
import re
import unicodedata
from collections import Counter
from typing import Any

from .geometry import compatibility
from .schemas import EOCollection, RankedCandidate, RetrievalProfile, SearchDocument, SearchQuery

TOKENIZER = "nfkc-lower-unicode-alnum-v1"
STRICT_FREE_TEXT_POLICY = "lexical-evidence-v1"
FREE_TEXT_POLICY = "lexical-evidence-v2"
FREE_TEXT_POLICIES = frozenset({STRICT_FREE_TEXT_POLICY, FREE_TEXT_POLICY})
QUERY_FILLER = frozenset(
    "can could dataset datasets find give information looking map maps mapping measure measures "
    "measurement measurements measuring method methods monitor monitoring observations observe "
    "please product products project projects records repeated research search show studies study "
    "using want which will would".split()
)
STOP_WORDS = frozenset(
    "a an and are as at be by for from in is it of on or that the to was were with".split()
)
TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
K1, B = 1.2, 0.75


def tokenize(text: str) -> list[str]:
    return [
        term
        for term in TOKEN.findall(unicodedata.normalize("NFKC", text).lower())
        if term not in STOP_WORDS
    ]


def document_text(doc: SearchDocument) -> str:
    measurements = doc.measurement_terms if isinstance(doc, EOCollection) else []
    return " ".join(
        filter(
            None,
            (
                doc.title,
                doc.description,
                " ".join([*doc.keywords, *doc.discovery_terms, *measurements]),
            ),
        )
    )


def evidence_term(token: str) -> str:
    if token == "european":
        return "europe"
    if len(token) >= 5 and token not in {"species", "series"}:
        if token.endswith("ies"):
            return token[:-3] + "y"
        if token.endswith(("ches", "shes", "xes", "sses", "zzes")):
            return token[:-2]
        if token.endswith("s") and not token.endswith(("ss", "us", "is")):
            return token[:-1]
    return token


def evidence_forms(index: dict) -> dict[str, list[str]]:
    forms: dict[str, list[str]] = {}
    for term in index["postings"]:
        forms.setdefault(evidence_term(term), []).append(term)
    return forms


def supported_rows(
    index: dict, forms: dict[str, list[str]], query: str, policy: str = FREE_TEXT_POLICY
) -> tuple[int, ...]:
    """Select candidates with overlap on informative query terms before ranking."""
    tokens = tokenize(query)
    anchors = [term for term in tokens if term not in QUERY_FILLER] or tokens
    if policy == FREE_TEXT_POLICY:
        anchors = [term for term in anchors if term not in {"s", "use", "testing"}]
    ordered = list(map(evidence_term, anchors))
    targets = dict.fromkeys(ordered)
    if not targets:
        return ()
    matches = {
        term: {row for spelling in forms.get(term, ()) for row, _ in index["postings"][spelling]}
        for term in targets
    }
    minimum = min(2, len(targets))
    if policy == FREE_TEXT_POLICY:
        counts = Counter(row for rows in matches.values() for row in rows)
        if len(targets) <= 4:
            return tuple(row for row in counts if counts[row] >= minimum)
        adjacent = set().union(
            *(
                matches[left] & matches[right]
                for left, right in zip(ordered, ordered[1:])
                if left != right
            )
        )
        return tuple(row for row in counts if counts[row] >= 3 or row in adjacent)

    counts = Counter()
    support = Counter()
    total_weight = 0.0
    size = len(index["lengths"])
    for rows in matches.values():
        weight = min(3.0, 1.0 + math.log1p(size / (len(rows) + 1)))
        total_weight += weight
        for row in rows:
            counts[row] += 1
            support[row] += weight
    return tuple(
        row for row in counts if counts[row] >= minimum and support[row] >= 0.5 * total_weight
    )


def with_topic_evidence(
    docs: list[SearchDocument], scores: dict[int, float], profile: RetrievalProfile
) -> dict[int, float]:
    groups = [
        [" " + " ".join(tokenize(term)) + " " for term in group]
        for group in profile.evidence_groups
    ]
    eligible = (
        {
            index: scores.get(index, 0.0)
            for index, doc in enumerate(docs)
            if doc.id in profile.record_evidence
        }
        if profile.record_evidence
        else {}
    )
    for index, score in scores.items():
        doc = docs[index]
        if index in eligible:
            continue
        fields = [
            " " + " ".join(tokenize(field)) + " "
            for field in (doc.title, doc.description, *doc.keywords)
            if field
        ]
        if all(any(term in field for term in group for field in fields) for group in groups):
            eligible[index] = score
    return eligible


def lexical_index(docs: list[SearchDocument]) -> dict:
    postings: dict[str, list] = {}
    lengths = []
    for i, doc in enumerate(docs):
        tokens = tokenize(document_text(doc))
        lengths.append(len(tokens))
        for token, frequency in Counter(tokens).items():
            postings.setdefault(token, []).append([i, frequency])
    return {
        "tokenizer": TOKENIZER,
        "k1": K1,
        "b": B,
        "lengths": lengths,
        "average": sum(lengths) / max(len(docs), 1),
        "postings": postings,
        "ids": [doc.id for doc in docs],
    }


def bm25(index: dict, query: str) -> dict[int, float]:
    scores: dict[int, float] = {}
    lengths = index["lengths"]
    k1, b, avg = index["k1"], index["b"], index["average"] or 1
    for term, multiplicity in Counter(tokenize(query)).items():
        rows = index["postings"].get(term, [])
        if not rows:
            continue
        idf = math.log1p((len(lengths) - len(rows) + 0.5) / (len(rows) + 0.5))
        for i, freq in rows:
            denom = freq + k1 * (1 - b + b * lengths[i] / avg)
            scores[i] = scores.get(i, 0) + multiplicity * idf * freq * (k1 + 1) / denom
    return scores


def evidence_snippet(doc: SearchDocument, query: str) -> str:
    evidence = doc.description or doc.title
    target = set(tokenize(query))
    fragments = re.split(r"(?<=[.!?])\s+", evidence)
    best = max(fragments, key=lambda text: len(target.intersection(tokenize(text))))
    return best[:400]


def rank(
    docs: list[SearchDocument],
    scores: dict[int, float],
    query: SearchQuery,
    kind: str,
    *,
    profile: RetrievalProfile | None = None,
) -> list[RankedCandidate]:
    evidence = profile.record_evidence if profile is not None else {}

    def ordering(index: int):
        assigned = evidence.get(docs[index].id)
        tier = 0 if assigned is None else 1 if assigned.role == "supporting_context" else 2
        return -tier, -scores[index], docs[index].id

    result = []
    for index in sorted(scores, key=ordering):
        doc = docs[index]
        match = compatibility(doc, query) if isinstance(doc, EOCollection) else "not_requested"
        if query.strict_metadata and match == "incompatible":
            continue
        result.append(
            RankedCandidate(
                id=doc.id,
                source=doc.provenance.source,
                title=doc.title,
                score=float(scores[index]),
                score_type=kind,
                rank=len(result) + 1,
                evidence=evidence_snippet(doc, query.query),
                source_url=doc.provenance.source_url,
                compatibility=match,
                flags=doc.metadata_quality_flags,
                provenance=doc.provenance,
                evidence_use=evidence.get(doc.id),
            )
        )
        if len(result) >= query.top_k:
            break
    return result


def hydrate(raw: dict[str, Any], corpus: str) -> list[SearchDocument]:
    from .schemas import ResearchProject

    cls = EOCollection if corpus == "eo" else ResearchProject
    return [cls.model_validate(row) for row in raw]
