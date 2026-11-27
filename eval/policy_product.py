"""Replay source-backed known targets on a browser payload and the same IDs with richer evidence."""

import argparse
from pathlib import Path
from time import perf_counter

import numpy as np

from eupolicyeo.bundle import CORPORA
from eupolicyeo.discovery import DiscoveryIndex
from eupolicyeo.encoder import REVISION, Encoder
from eupolicyeo.measurements import catalogue_measurements
from eupolicyeo.retrieval import bm25, evidence_forms, hydrate, rank, supported_rows
from eupolicyeo.schemas import SearchQuery
from eupolicyeo.storage import file_hash, read_json, snapshot_dir, write_json

TARGETS = Path(__file__).with_name("policy_product_targets.json")


def evaluate(
    seed: dict, release: Path, *, build_passages=True, baseline: Path | None = None
) -> dict:
    manifest = read_json(release / "manifest.json")
    if manifest["parent_snapshot_id"] != seed["snapshot"]:
        raise ValueError("target definitions refer to a different source snapshot")
    source = snapshot_dir(seed["snapshot"])
    model = Encoder(release / "models")
    measures = catalogue_measurements(source)
    all_results = {}
    build = {}
    for corpus, filename in CORPORA.items():
        rows = hydrate(read_json(release / f"{filename}.json"), corpus)
        archive = {doc.id: doc for doc in hydrate(read_json(source / f"{filename}.json"), corpus)}
        index = read_json(release / f"lexical/{corpus}.json")
        forms = evidence_forms(index)
        vectors = np.fromfile(release / f"vectors/{corpus}.f32", dtype="<f4").reshape(len(rows), -1)
        prior_ids = (
            None
            if baseline is None
            else {row["id"] for row in read_json(baseline / f"{filename}.json")}
        )
        started = perf_counter()
        passage_index = (
            DiscoveryIndex([archive[d.id] for d in rows], measures, model)
            if build_passages
            else None
        )
        if passage_index:
            build[corpus] = {
                "records": len(rows),
                "passages": len(passage_index.passages),
                "elapsed_seconds": round(perf_counter() - started, 4),
            }
        for case in (case for case in seed["cases"] if case["corpus"] == corpus):
            prefix = case["target_prefix"]
            target = {key for key in archive if key == prefix or key.startswith(prefix + "_")}
            if not target:
                raise ValueError(f"No archived target for {case['id']}")
            req = SearchQuery(query=case["query"], corpus=corpus, top_k=50)
            started = perf_counter()
            policy = manifest.get("free_text_policy")
            lexical_raw = bm25(index, req.query)
            dense_raw = vectors @ model.encode([req.query])[0]
            scoped = supported_rows(index, forms, req.query, policy) if policy else range(len(rows))
            keyword = rank(
                rows,
                {i: lexical_raw.get(i, 0.0) for i in scoped if policy or i in lexical_raw},
                req,
                "bm25",
            )
            semantic = rank(rows, {i: float(dense_raw[i]) for i in scoped}, req, "cosine")
            outcomes = {
                "public_keyword": [row.id for row in keyword],
                "public_semantic": [row.id for row in semantic],
            }
            search_ms = {"public_rankers_combined": (perf_counter() - started) * 1000}
            if passage_index:
                started = perf_counter()
                result = passage_index.search(req)
                search_ms["passage_hybrid"] = (perf_counter() - started) * 1000
                outcomes["passage_hybrid"] = [row["id"] for row in result["results"]]
            all_results[case["id"]] = {
                "targets": sorted(target),
                "source_urls": [archive[key].provenance.source_url for key in sorted(target)],
                "in_public": any(doc.id in target for doc in rows),
                "in_prior_public": None if prior_ids is None else bool(target & prior_ids),
                "ranks": {
                    mode: next(
                        (i for i, identifier in enumerate(ids, 1) if identifier in target), None
                    )
                    for mode, ids in outcomes.items()
                },
                "top_five": {mode: ids[:5] for mode, ids in outcomes.items()},
                "ms": search_ms,
            }
    modes = next(iter(all_results.values()))["ranks"].keys()
    metrics = {}
    for mode in modes:
        ranks = [result["ranks"][mode] for result in all_results.values()]
        metrics[mode] = {
            f"hit_at_{k}": sum(r is not None and r <= k for r in ranks) for k in (1, 5, 50)
        }
    return {
        "protocol": seed["id"],
        "query_sha256": file_hash(TARGETS),
        "scope": seed["scope"],
        "snapshot": seed["snapshot"],
        "release_id": manifest["release_id"],
        "encoder": REVISION,
        "target_cases": len(all_results),
        "targets_in_public": sum(row["in_public"] for row in all_results.values()),
        "build": build,
        "metrics": metrics,
        "cases": all_results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--without-passages", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(
        read_json(TARGETS),
        args.release,
        build_passages=not args.without_passages,
        baseline=args.baseline,
    )
    write_json(args.output, report)
    print(report["target_cases"], report["targets_in_public"], report["metrics"])


if __name__ == "__main__":
    main()
