import json
import math
import os
import platform
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from time import perf_counter

import numpy as np

from .bundle import CORPORA, Bundle
from .schemas import SearchQuery
from .settings import artifacts
from .storage import file_hash, write_json

PROBES = (
    "urban tree canopy cover in cities",
    "forest structural diversity and biomass",
    "wetland inundation and water extent",
    "satellite habitat mapping",
    "biodiversity indicators for agricultural ecosystems",
    "marine habitat seafloor mapping",
    "pollinator populations and species diversity",
    "peatland restoration and drainage",
    "vegetation health through drought",
    "land surface temperature and impervious surfaces",
    "forest fragmentation and connectivity",
    "soil organic carbon monitoring",
    "coastal erosion and vegetation",
    "grassland mowing and ecosystem restoration",
    "sentinel optical imagery",
    "radar monitoring of flooding",
    "global land cover classification",
    "mangrove canopy structure",
    "résilience végétale 2024/1991",
    "zyxwvu qqqqq",
    "surface water " * 165 + "seasonal monitoring",
)


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def measures(ranked: list[str], qrels: dict[str, int]) -> dict:
    top = ranked[:10]
    found = [i for i, id_ in enumerate(top, 1) if qrels.get(id_, 0) >= 1]
    positives = sum(label >= 1 for label in qrels.values())
    judged_count = sum(id_ in qrels for id_ in top)

    def dcg(labels):
        return sum((2**label - 1) / math.log2(i + 2) for i, label in enumerate(labels))

    ideal = dcg(sorted(qrels.values(), reverse=True)[:10])
    return {
        "mrr10": 1 / found[0] if found else 0.0,
        "ndcg10": dcg(qrels.get(id_, 0) for id_ in top) / ideal if ideal else None,
        "pooled_recall5": sum(i <= 5 for i in found) / positives if positives else None,
        "pooled_recall10": len(found) / positives if positives else None,
        "judged_precision10": len(found) / judged_count if judged_count else None,
        "judged_coverage10": judged_count / len(top) if top else 0.0,
    }


def evaluate(bundle: Bundle, directory: Path) -> dict:
    queries = read_jsonl(directory / "queries.jsonl")
    qrels = read_jsonl(directory / "qrels.jsonl")
    gold = read_jsonl(directory / "requirements.jsonl")
    results = {}
    for corpus in CORPORA:
        reviewed = []
        for query in queries:
            if query["corpus"] != corpus or not query.get("reviewed") or not query.get("reviewer"):
                continue
            labels = {
                row["candidate_id"]: row["relevance"]
                for row in qrels
                if row["query_id"] == query["query_id"]
                and row["corpus"] == corpus
                and row.get("reviewed")
                and row.get("reviewer")
                and row.get("reason")
                and row.get("evidence_url")
                and type(row.get("relevance")) is int
                and row["relevance"] in (0, 1, 2)
            }
            corpus_ids = {doc.id for doc in bundle.docs[corpus]}
            if labels.keys() - corpus_ids:
                raise ValueError("reviewed qrels cite documents outside the selected snapshot")
            if labels:
                requirement = bundle.requirements.get(query.get("requirement_id"))
                profile = requirement.search_profile if requirement else None
                if profile and profile.query != query["query"]:
                    profile = None
                ranking = bundle.search(
                    SearchQuery(query=query["query"], corpus=corpus, top_k=10), profile=profile
                )
                reviewed.append(
                    {
                        "query_id": query["query_id"],
                        "split": query["split"],
                        "positives": sum(v >= 1 for v in labels.values()),
                        "metrics": measures([item.id for item in ranking], labels),
                    }
                )
        test = [row for row in reviewed if row["split"] == "test"]
        metrics = {}
        for key in measures([], {}):
            observed = [row["metrics"][key] for row in test if row["metrics"][key] is not None]
            if observed:
                metrics[key] = mean(observed)
        results[corpus] = {
            "query_count": len(test),
            "no_positives": sum(not r["positives"] for r in test),
            "mean": metrics,
            "per_query": reviewed,
        }
    extraction = []
    for label in gold:
        if not label.get("reviewed") or not label.get("reviewer"):
            continue
        prediction = bundle.requirements.get(label["requirement_id"])
        fields = {
            key: prediction is not None and getattr(prediction, key) == value
            for key, value in label["fields"].items()
        }
        extraction.append({"requirement_id": label["requirement_id"], "matches": fields})
    report = {
        "snapshot_id": bundle.snapshot,
        "ranker": bundle.ranker,
        "build_id": bundle.manifest["build_id"],
        "at": datetime.now(UTC).isoformat(),
        "corpora": results,
        "review_status": "reviewed"
        if any(r["query_count"] for r in results.values())
        else "pending human review",
        "scope": "test queries; label >= 1; unjudged has no gain in nDCG/MRR and is excluded from judged precision",
        "annotation_hashes": {
            name: file_hash(directory / name)
            for name in ("queries.jsonl", "qrels.jsonl", "requirements.jsonl")
        },
        "extraction": {
            "reviewed_count": len(extraction),
            "per_requirement": extraction,
            "field_accuracy": mean(x for r in extraction for x in r["matches"].values())
            if any(r["matches"] for r in extraction)
            else None,
        },
    }
    write_json(artifacts() / "reports" / f"{bundle.manifest['build_id']}-evaluation.json", report)
    return report


def annotation_pool(bundles: list[Bundle], path: Path) -> dict:
    first = bundles[0]
    queries, candidates, requirements = [], {}, []
    for req in first.requirements.values():
        requirements.append(
            {
                "requirement_id": req.id,
                "section_id": req.section_id,
                "evidence_url": first.sections[req.section_id].provenance.source_url,
                "fields": req.model_dump(
                    include={
                        "evidence_start",
                        "evidence_end",
                        "modality",
                        "action",
                        "observable",
                        "conditions",
                    }
                ),
                "reviewed": False,
                "reviewer": None,
            }
        )
        for corpus in CORPORA:
            id_ = f"{req.id}:{corpus}"
            profile = req.search_profile
            query = profile.query if profile and profile.query else req.query
            queries.append(
                {
                    "query_id": id_,
                    "requirement_id": req.id,
                    "section_id": req.section_id,
                    "query": query,
                    "split": "test",
                    "corpus": corpus,
                    "reviewed": False,
                    "reviewer": None,
                }
            )
            for bundle in bundles:
                for item in bundle.search(
                    SearchQuery(query=query[:2000], corpus=corpus, top_k=5), profile=profile
                ):
                    key = (id_, item.id)
                    candidates.setdefault(
                        key,
                        {
                            "query_id": id_,
                            "corpus": corpus,
                            "candidate_id": item.id,
                            "title": item.title,
                            "evidence_url": item.source_url,
                            "evidence": item.evidence,
                            "relevance": None,
                            "reason": None,
                            "reviewed": False,
                            "reviewer": None,
                        },
                    )
    path.mkdir(parents=True, exist_ok=True)
    for name, rows in (
        ("queries", queries),
        ("qrels", candidates.values()),
        ("requirements", requirements),
    ):
        target = path / f"{name}.jsonl"
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {
        "requirements": len(requirements),
        "queries": len(queries),
        "candidates": len(candidates),
    }


def benchmark(bundle: Bundle, repeats: int) -> dict:
    from importlib.metadata import version

    import psutil

    process = psutil.Process(os.getpid())
    peak = process.memory_info().rss
    latencies, errors = [], []
    for i in range(repeats):
        for corpus in CORPORA:
            for text in PROBES:
                start = perf_counter()
                try:
                    bundle.search(SearchQuery(query=text[:2000], corpus=corpus))
                except (ValueError, RuntimeError) as exc:
                    errors.append(type(exc).__name__)
                    continue
                elapsed = (perf_counter() - start) * 1000
                if i:
                    latencies.append(elapsed)
                peak = max(peak, process.memory_info().rss)
    timing = (
        {f"p{p}": round(float(np.percentile(latencies, p)), 4) for p in (50, 95, 99)}
        if latencies
        else {}
    )
    report = {
        "snapshot_id": bundle.snapshot,
        "build_id": bundle.manifest["build_id"],
        "ranker": bundle.ranker,
        "at": datetime.now(UTC).isoformat(),
        "counts": bundle.manifest["counts"],
        "search_ms": timing,
        "sample_count": len(latencies),
        "errors": len(errors),
        "setup": {
            "warmup_passes": 1,
            "measured_passes": repeats - 1,
            "concurrency": 1,
            "device": "CPU",
            "threads_for_onnx": bundle.manifest["encoder_threads"],
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu": platform.processor(),
            "onnxruntime": version("onnxruntime"),
            "rss_sampling": "process RSS sampled after each successful query",
        },
        "peak_sampled_rss_bytes": peak,
        "build_seconds": bundle.manifest["build_seconds"],
        "embedding_seconds": bundle.manifest["embedding_seconds"],
        "bundle_bytes": sum(p.stat().st_size for p in bundle.root.rglob("*") if p.is_file()),
    }
    write_json(artifacts() / "reports" / f"{bundle.manifest['build_id']}-benchmark.json", report)
    return report
