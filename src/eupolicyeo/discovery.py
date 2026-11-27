"""Field and passage retrieval over source-linked catalogue records."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .encoder import Encoder
from .geometry import compatibility
from .measurements import Measurement
from .retrieval import bm25, lexical_index
from .schemas import EOCollection, SearchDocument, SearchQuery

CHUNK_WORDS = 105
CHUNK_OVERLAP = 15
POOL_SIZE = 60
FUSION_K = 60


@dataclass(frozen=True)
class Passage:
    record: int
    field: str
    text: str


def description_passages(text: str) -> Iterable[str]:
    """Pack short sentences and split exceptionally long ones with limited overlap."""
    block: list[str] = []
    count = 0
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text.strip()):
        words = sentence.split()
        if not words:
            continue
        if len(words) > CHUNK_WORDS:
            if block:
                yield " ".join(block)
                block, count = [], 0
            for start in range(0, len(words), CHUNK_WORDS - CHUNK_OVERLAP):
                yield " ".join(words[start : start + CHUNK_WORDS])
                if start + CHUNK_WORDS >= len(words):
                    break
            continue
        if count + len(words) > CHUNK_WORDS and block:
            yield " ".join(block)
            block, count = [], 0
        block.append(sentence)
        count += len(words)
    if block:
        yield " ".join(block)


def passages(docs: list[SearchDocument], measures: dict[str, list[Measurement]]) -> list[Passage]:
    result = []
    for number, doc in enumerate(docs):
        result.append(Passage(number, "title", doc.title))
        topics = list(dict.fromkeys([*doc.keywords, *doc.discovery_terms]))
        if topics:
            result.append(Passage(number, "catalogue topics", " · ".join(topics)))
        if rows := measures.get(doc.id):
            result.append(Passage(number, rows[0].field, " · ".join(item.label for item in rows)))
        if doc.description:
            field = (
                "collection description" if isinstance(doc, EOCollection) else "project objective"
            )
            result.extend(
                Passage(number, field, part) for part in description_passages(doc.description)
            )
    return result


class DiscoveryIndex:
    def __init__(
        self, docs: list[SearchDocument], measures: dict[str, list[Measurement]], encoder: Encoder
    ):
        self.docs = docs
        self.passages = passages(docs, measures)
        self.encoder = encoder
        self.lexical = lexical_index(
            [
                SearchDocument(id=str(i), title=row.text, provenance=docs[row.record].provenance)
                for i, row in enumerate(self.passages)
            ]
        )
        self.vectors = encoder.encode([row.text for row in self.passages])

    def _pool(self, scores: Iterable[tuple[int, float]], eligible: set[int]):
        """Keep the best evidence passage per record before pooling ranks."""
        best = {}
        for passage_id, raw_score in scores:
            row = self.passages[passage_id]
            score = float(raw_score)
            previous = best.get(row.record)
            if row.record in eligible and (previous is None or score > previous[0]):
                best[row.record] = (score, passage_id)
        ranked = sorted(best, key=lambda i: (-best[i][0], self.docs[i].id))[:POOL_SIZE]
        return dict((i, best[i]) for i in ranked)

    def search(self, request: SearchQuery) -> dict:
        eligible = {
            i
            for i, doc in enumerate(self.docs)
            if not (
                request.strict_metadata
                and isinstance(doc, EOCollection)
                and compatibility(doc, request) == "incompatible"
            )
        }
        lexical = self._pool(bm25(self.lexical, request.query).items(), eligible)
        vector = self.encoder.encode([request.query])[0]
        semantic = self._pool(enumerate(self.vectors @ vector), eligible)
        fused = {}
        for weight, ranking in ((1.0, lexical), (1.0, semantic)):
            for index, row in enumerate(ranking, 1):
                fused[row] = fused.get(row, 0) + weight / (FUSION_K + index)
        selected = sorted(fused, key=lambda i: (-fused[i], self.docs[i].id))[: request.top_k]
        results = []
        for i in selected:
            doc = self.docs[i]
            evidence = {}
            for name, ranking in (("keyword", lexical), ("semantic", semantic)):
                if i in ranking:
                    score, passage_id = ranking[i]
                    passage = self.passages[passage_id]
                    evidence[name] = {"field": passage.field, "text": passage.text, "score": score}
            results.append(
                {
                    "id": doc.id,
                    "title": doc.title,
                    "source_url": doc.provenance.source_url,
                    "rank_score": fused[i],
                    "evidence": evidence,
                }
            )
        return {
            "results": results,
            "pool": {
                "keyword": [self.docs[i].id for i in lexical],
                "semantic": [self.docs[i].id for i in semantic],
            },
        }
