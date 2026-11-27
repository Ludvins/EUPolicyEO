"""Compare frozen free-text queries across two captured Pages releases."""

import argparse
import json
from collections import Counter
from pathlib import Path

from eupolicyeo.storage import digest, file_hash, json_bytes, read_json
from scripts.holdout_review import DOCS, MODES, review_packet

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "search-quality"
QUESTIONS = Path(__file__).with_name("search_quality_queries.json")
BASELINE = ROOT / "artifacts" / "coverage-release" / "pages"
STAGES = ("baseline", "candidate")
RUBRIC = {
    "0": "Unrelated, incompatible, or no documented connection to the request.",
    "1": "Concrete useful partial evidence or a transferable method, with a documented gap.",
    "2": "Direct documented measurement or research method within the requested scope.",
}


def freeze(path: Path, data) -> None:
    content = json_bytes(data)
    if path.exists():
        if path.read_bytes() != content:
            raise FileExistsError(f"Frozen evidence differs at {path}. Use a new output directory.")
        return
    with path.open("xb") as stream:
        stream.write(content)


def archive_records(root: Path) -> dict[str, dict]:
    return {row["id"]: row for filename in DOCS.values() for row in read_json(root / filename)}


def make_case(
    spec: dict, stages: dict, records: dict, blind_case_id: str | None = None
) -> tuple[dict, dict]:
    identifiers = {record["id"] for stage in stages.values() for record in stage["candidates"]}
    order = sorted(identifiers, key=lambda id_: (digest(json_bytes([spec["id"], id_])), id_))
    case_label = blind_case_id or spec["id"]
    pair_by_record = {id_: f"{case_label}-{position:02}" for position, id_ in enumerate(order, 1)}
    public = {record["id"]: record for stage in stages.values() for record in stage["candidates"]}
    candidates = []
    for id_ in order:
        source = records.get(id_)
        if source is None or source["title"] != public[id_]["title"]:
            raise ValueError(f"Missing or mismatched archived evidence for {id_}.")
        fields = (
            ("description", "keywords", "bbox_parts", "intervals", "spatial_resolution_m")
            if spec["corpus"] == "eo"
            else ("description", "keywords", "acronym", "start_date", "end_date")
        )
        candidate = {key: public[id_][key] for key in ("id", "title", "source_url", "metadata")}
        candidate.update(
            pair=pair_by_record[id_],
            archived_evidence={key: source.get(key) for key in fields},
            archive_source_url=source["provenance"]["source_url"],
        )
        candidates.append(candidate)
    blind = {key: spec[key] for key in ("corpus", "query", "intent", "filters") if key in spec}
    blind["id"] = case_label
    blind["candidates"] = candidates
    audit = {
        "id": spec["id"],
        "corpus": spec["corpus"],
        "control": spec.get("control"),
        "pairs": list(pair_by_record.values()),
        "records": pair_by_record,
        "rankings": {
            stage: {mode: [pair_by_record[id_] for id_ in saved["ranks"][mode]] for mode in MODES}
            for stage, saved in stages.items()
        },
    }
    return blind, audit


def balanced_buckets(cases: list[dict], count: int) -> dict[str, list[dict]]:
    names = [f"review-{index:02}" for index in range(1, count + 1)]
    buckets = {name: [] for name in names}
    lengths: dict[str, int] = dict.fromkeys(names, 0)
    for case in sorted(cases, key=lambda row: (-len(row["candidates"]), row["id"])):
        chosen = min(names, key=lambda name: (lengths[name], len(buckets[name]), name))
        buckets[chosen].append(case)
        lengths[chosen] += len(case["candidates"])
    return buckets


def prepare(args):
    definitions = read_json(args.questions)
    queries = definitions["queries"]
    if not 8 <= len(queries) <= 10 or sum("control" in row for row in queries) != 2:
        raise ValueError("The protocol expects 8–10 questions and two controls.")
    paths = {
        "baseline": (args.baseline, args.baseline_rankings),
        "candidate": (args.candidate, args.candidate_rankings),
    }
    captures = {
        stage: review_packet(release, capture, args.questions)
        for stage, (release, capture) in paths.items()
    }
    snapshots = {
        read_json(release / "manifest.json")["parent_snapshot_id"] for release, _ in paths.values()
    }
    if len(snapshots) != 1:
        raise ValueError("Use one source snapshot for the paired-release comparison.")
    (snapshot,) = snapshots
    if captures["baseline"]["release_id"] == captures["candidate"]["release_id"]:
        raise ValueError("The two captures must point to distinct immutable releases.")
    archive = args.archive / snapshot
    records = archive_records(archive)
    scoped = {
        stage: {case["id"]: case for case in capture["cases"]}
        for stage, capture in captures.items()
    }
    cases = [
        make_case(
            spec,
            {stage: scoped[stage][spec["id"]] for stage in STAGES},
            records,
            f"case-{index:02}" if args.blind_case_ids else None,
        )
        for index, spec in enumerate(queries, 1)
    ]
    blinded = balanced_buckets([blind for blind, _ in cases], args.buckets)
    args.output.mkdir(parents=True, exist_ok=True)
    buckets = {}
    for name, items in blinded.items():
        if not any(case["candidates"] for case in items):
            raise ValueError("Use fewer review buckets so each contains a candidate pair.")
        blind = {"rubric": RUBRIC, "bucket": name, "cases": items}
        path = args.output / f"{name}.json"
        freeze(path, blind)
        buckets[name] = {
            "packet": path.name,
            "sha256": file_hash(path),
            "pairs": sorted(row["pair"] for case in items for row in case["candidates"]),
        }
    audit = {
        "protocol_id": definitions["id"],
        "query_sha256": file_hash(args.questions),
        "snapshot": snapshot,
        "archive_data_sha256": {
            filename: file_hash(archive / filename) for filename in DOCS.values()
        },
        "stages": {
            stage: {
                key: capture[key] for key in ("release_id", "manifest_sha256", "rankings_sha256")
            }
            for stage, capture in captures.items()
        },
        "buckets": buckets,
        "cases": [row for _, row in cases],
    }
    freeze(args.output / "ranking-audit.json", audit)
    return {
        "queries": len(queries),
        "buckets": {name: len(data["pairs"]) for name, data in buckets.items()},
        "candidate_pairs": sum(len(row["pairs"]) for row in audit["cases"]),
        "rankings": {
            stage: {
                mode: sum(len(row["rankings"][stage][mode]) for row in audit["cases"])
                for mode in MODES
            }
            for stage in STAGES
        },
        "empty_queries": {
            stage: {
                mode: sum(not row["rankings"][stage][mode] for row in audit["cases"])
                for mode in MODES
            }
            for stage in STAGES
        },
    }


def model_grades(output: Path, audit: dict, votes: Path) -> tuple[dict, list]:
    files = sorted(votes.glob("*.json"))
    reviewers = set()
    groups = Counter()
    ratings = {}
    provenance = []
    for name, data in audit["buckets"].items():
        if file_hash(output / data["packet"]) != data["sha256"]:
            raise ValueError(f"Frozen blind packet changed for {name}.")
        for pair in data["pairs"]:
            if pair in ratings:
                raise ValueError(f"Pair was assigned to more than one bucket: {pair}.")
            ratings[pair] = Counter()
    for file in files:
        vote = read_json(file)
        if set(vote) != {"reviewer", "bucket", "ratings"}:
            raise ValueError(f"Invalid model ballot format: {file}.")
        name = vote["reviewer"]
        bucket = vote["bucket"]
        if not isinstance(name, str) or not name.strip() or name in reviewers:
            raise ValueError(f"Missing or duplicate reviewer ID in {file}.")
        if bucket not in audit["buckets"]:
            raise ValueError(f"Unknown ballot bucket in {file}.")
        judges = vote["ratings"]
        if not isinstance(judges, dict) or set(judges) != set(audit["buckets"][bucket]["pairs"]):
            raise ValueError(f"Ballot does not match the exact bucket pair IDs: {file}.")
        reviewers.add(name)
        groups[bucket] += 1
        provenance.append({"reviewer": name, "bucket": bucket, "sha256": file_hash(file)})
        for pair, entry in judges.items():
            if not isinstance(entry, dict) or set(entry) != {"label", "reason"}:
                raise ValueError(f"Invalid rating fields for {pair} from {name}.")
            label = entry.get("label")
            reason = entry.get("reason")
            if type(label) is not int or label not in (0, 1, 2):
                raise ValueError(f"Invalid label for {pair} from {name}.")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"Missing evidence reason for {pair} from {name}.")
            ratings[pair][label] += 1
    if any(groups[bucket] != 3 for bucket in audit["buckets"]):
        raise ValueError(
            f"Provide exactly three independent ballots per bucket. Found {dict(groups)}."
        )
    return ratings, provenance


def score_mode(cases: list[dict], consensus: dict, stage: str, mode: str) -> dict:
    ranks = {case["id"]: case["rankings"][stage][mode] for case in cases}
    topical = [case for case in cases if not case["control"]]
    controls = [case for case in cases if case["control"]]
    complete = [
        case for case in cases if all(consensus.get(pair) is not None for pair in case["pairs"])
    ]
    assessed = [case for case in complete if not case["control"]]
    labels = [[consensus[pair] for pair in ranks[case["id"]]] for case in assessed]
    return {
        "questions": len(cases),
        "topical_questions": len(topical),
        "fully_judged_topical_questions": len(assessed),
        "control_questions": len(controls),
        "direct_top_1": sum(2 in row[:1] for row in labels),
        "direct_top_3": sum(2 in row[:3] for row in labels),
        "useful_top_5": sum(any(label >= 1 for label in row) for row in labels),
        "topical_results": sum(map(len, labels)),
        "unrelated_topical_results": sum(row.count(0) for row in labels),
        "empty_topical_queries": sum(not ranks[case["id"]] for case in topical),
        "empty_control_queries": sum(not ranks[case["id"]] for case in controls),
        "control_results": sum(len(ranks[case["id"]]) for case in controls),
        "unrelated_control_results": sum(
            consensus.get(pair) == 0 for case in controls for pair in ranks[case["id"]]
        ),
        "unresolved_control_results": sum(
            consensus.get(pair) is None for case in controls for pair in ranks[case["id"]]
        ),
    }


def score(args):
    audit_path = args.output / "ranking-audit.json"
    audit = read_json(audit_path)
    ratings, provenance = model_grades(args.output, audit, args.votes)
    consensus = {
        pair: next((label for label, count in counts.items() if count >= 2), None)
        for pair, counts in ratings.items()
    }
    totals = Counter(consensus.values())
    pair_count = len(ratings)
    agreements = sum(
        count * (count - 1) // 2 for value in ratings.values() for count in value.values()
    )
    report = {
        "judgment_type": "model review",
        "human_judgments": 0,
        "audit_sha256": file_hash(audit_path),
        "reviewer_ballots": provenance,
        "candidate_pairs": pair_count,
        "ratings": pair_count * 3,
        "pairwise_agreement": {"agreed": agreements, "possible": pair_count * 3},
        "consensus_totals": {
            "unrelated": totals[0],
            "partial": totals[1],
            "direct": totals[2],
            "unresolved": totals[None],
        },
        "consensus_by_pair": consensus,
        "rankers": {
            stage: {mode: score_mode(audit["cases"], consensus, stage, mode) for mode in MODES}
            for stage in STAGES
        },
        "results": [
            {key: value for key, value in case.items() if key != "records"}
            for case in audit["cases"]
        ],
        "scope": (
            "Quality counts use topical questions whose shared two-release pool has a "
            "majority judgment for every pair. Empty returns use all questions. "
            "All judgments are from the model panel."
        ),
    }
    freeze(args.output / "model-review-results.json", report)
    return {
        key: report[key]
        for key in (
            "judgment_type",
            "human_judgments",
            "candidate_pairs",
            "ratings",
            "pairwise_agreement",
            "consensus_totals",
            "rankers",
        )
    }


def aggregate(args):
    audit_path = args.output / "ranking-audit.json"
    audit = read_json(audit_path)
    result_path = args.output / "model-review-results.json"
    result = read_json(result_path)
    manifest_path = args.candidate / "manifest.json"
    manifest = read_json(manifest_path)
    if result["audit_sha256"] != file_hash(audit_path) or (
        audit["stages"]["candidate"]["manifest_sha256"] != file_hash(manifest_path)
    ):
        raise ValueError("The evaluation and release must match the frozen ranking audit.")
    stages = audit["stages"]
    report = {
        "protocol_id": audit["protocol_id"],
        "release_id": manifest["release_id"],
        "baseline_release_id": stages["baseline"]["release_id"],
        "snapshot_id": manifest["parent_snapshot_id"],
        "public_corpus_hash": manifest["public_corpus_hash"],
        "query_sha256": audit["query_sha256"],
        "result_sha256": file_hash(result_path),
        **{
            key: result[key]
            for key in (
                "judgment_type",
                "human_judgments",
                "candidate_pairs",
                "ratings",
                "pairwise_agreement",
                "consensus_totals",
                "rankers",
            )
        },
    }
    freeze(args.report, report)
    return {"release_id": manifest["release_id"], "report_sha256": file_hash(args.report)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--questions", type=Path, default=QUESTIONS)
    prepare_parser.add_argument("--baseline", type=Path, default=BASELINE)
    prepare_parser.add_argument("--candidate", type=Path, default=OUT / "pages")
    prepare_parser.add_argument(
        "--baseline-rankings", type=Path, default=OUT / "baseline-rankings.json"
    )
    prepare_parser.add_argument(
        "--candidate-rankings", type=Path, default=OUT / "candidate-rankings.json"
    )
    prepare_parser.add_argument("--archive", type=Path, default=ROOT / "artifacts" / "snapshots")
    prepare_parser.add_argument("--output", type=Path, default=OUT / "review")
    prepare_parser.add_argument("--buckets", type=int, default=3, choices=(2, 3, 4))
    prepare_parser.add_argument("--blind-case-ids", action="store_true")
    score_parser = commands.add_parser("score")
    score_parser.add_argument("--output", type=Path, default=OUT / "review")
    score_parser.add_argument("--votes", type=Path, default=OUT / "review" / "votes")
    aggregate_parser = commands.add_parser("aggregate")
    aggregate_parser.add_argument("--output", type=Path, required=True)
    aggregate_parser.add_argument("--candidate", type=Path, required=True)
    aggregate_parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = {"prepare": prepare, "score": score, "aggregate": aggregate}[args.command](args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
