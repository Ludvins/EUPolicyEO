"""Prepare and score the public search holdout with recorded human judgments."""

import argparse
import html
import json
import math
from pathlib import Path
from urllib.parse import quote

from eupolicyeo.publication import validate
from eupolicyeo.schemas import SearchQuery
from eupolicyeo.storage import digest, file_hash, json_bytes, read_json

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "eval" / "holdout_queries.json"
TEMPLATE = ROOT / "eval" / "holdout_review.html"
ARTIFACTS = ROOT / "artifacts" / "coverage-evaluation"
PAGES = ROOT / "artifacts" / "coverage-release" / "pages"
MODES = ("bm25", "dense")
DOCS = {"eo": "collections.json", "projects": "projects.json"}


def candidate(doc: dict) -> dict:
    provenance = doc["provenance"]
    source = provenance["source"]
    source_id = quote(provenance["source_id"], safe="")
    page = {
        "cdse": f"https://browser.stac.dataspace.copernicus.eu/collections/{source_id}",
        "cmr": f"https://cmr.earthdata.nasa.gov/search/concepts/{source_id}",
        "cordis": f"https://cordis.europa.eu/project/id/{source_id}",
    }[source]
    fields = {
        "Provider": doc.get("provider"),
        "Spatial resolution (m)": doc.get("spatial_resolution_m"),
        "Catalogue start": doc.get("temporal_start"),
        "Catalogue end": doc.get("temporal_end"),
        "Project start": doc.get("start_date"),
        "Project end": doc.get("end_date"),
    }
    return {
        "id": doc["id"],
        "title": doc["title"],
        "source_url": page,
        "metadata": {key: value for key, value in fields.items() if value is not None},
    }


def review_packet(release: Path, capture: Path, definitions: Path) -> dict:
    manifest = validate(release)
    settings = read_json(definitions)
    top = settings["top_k"]
    saved = read_json(capture)
    release_hash = file_hash(release / "manifest.json")
    questions_hash = file_hash(definitions)
    if (
        saved["release_id"] != manifest["release_id"]
        or saved["manifest_sha256"] != release_hash
        or saved["protocol_id"] != settings["id"]
        or saved["query_sha256"] != questions_hash
        or saved["top_k"] != top
        or top != 5
    ):
        raise ValueError("Capture does not match the verified release and frozen questions.")
    questions = settings["queries"]
    order = [row["id"] for row in questions]
    if len(set(order)) != len(order) or [row["query_id"] for row in saved["results"]] != order:
        raise ValueError("Captured and frozen question IDs differ or contain duplicates.")
    docs = {
        corpus: {record["id"]: record for record in read_json(release / path)}
        for corpus, path in DOCS.items()
    }
    packet = {
        "protocol_id": settings["id"],
        "query_sha256": questions_hash,
        "release_id": manifest["release_id"],
        "manifest_sha256": release_hash,
        "rankings_sha256": file_hash(capture),
        "top_k": top,
        "cases": [],
    }
    for spec, saved_case in zip(questions, saved["results"], strict=True):
        corpus = spec["corpus"]
        SearchQuery(query=spec["query"], corpus=corpus, top_k=top, **spec.get("filters", {}))
        ranked = {}
        for mode in MODES:
            rows = saved_case[mode]
            ids = [row["id"] for row in rows]
            if (
                len(ids) > top
                or len(ids) != len(set(ids))
                or any(id_ not in docs[corpus] for id_ in ids)
                or any(not math.isfinite(row["score"]) for row in rows)
            ):
                raise ValueError(f"Invalid {mode} ranking for {spec['id']}.")
            ranked[mode] = ids
        pool = set().union(*ranked.values())
        # The hash order is shared across releases and independent of ranking positions.
        blind_order = sorted(
            pool,
            key=lambda id_: (digest(json_bytes([settings["id"], spec["id"], id_])), id_),
        )
        items = [
            {"pair": f"{spec['id']}-{index:02}", **candidate(docs[corpus][id_])}
            for index, id_ in enumerate(blind_order, 1)
        ]
        packet["cases"].append({**spec, "candidates": items, "ranks": ranked})
    return packet


def review_page(packet: dict, packet_sha: str) -> str:
    escape = html.escape
    labels = {"eo": "Earth observation catalogue", "projects": "Research projects"}
    questions = []
    for index, case in enumerate(packet["cases"]):
        cards = []
        for row in case["candidates"]:
            pair = escape(row["pair"])
            source = escape(row["source_url"])
            title = escape(row["title"])
            metadata = " · ".join(
                f"{escape(key)} {escape(str(value))}" for key, value in row["metadata"].items()
            )
            cards.append(
                f"""
<article data-pair="{pair}">
  <h2><a href="{source}" target="_blank" rel="noopener noreferrer">{title}</a></h2>
  <p class="muted">{metadata}</p>
  <div class="fields">
    <label>Rating
      <select aria-label="Rating for {title}">
        <option value="">Unscored</option>
        <option value="2">2 · Direct evidence</option>
        <option value="1">1 · Useful partial evidence</option>
        <option value="0">0 · Unrelated</option>
      </select>
    </label>
    <label>Reason
      <textarea rows="2" maxlength="800" aria-label="Reason for {title}"></textarea>
    </label>
  </div>
</article>"""
            )
        filters = case.get("filters", {})
        scope = []
        if "bbox" in filters:
            coordinates = ", ".join(str(value) for value in filters["bbox"])
            scope.append(f"Search bounds (west, south, east, north) {coordinates}")
        if "start" in filters and "end" in filters:
            scope.append(f"Search dates {filters['start'][:10]} to {filters['end'][:10]}")
        joined = escape(" · ".join([labels[case["corpus"]], *scope]))
        content = "\n".join(cards) or "<p>This question has no candidate records to rate.</p>"
        question = escape(case["query"])
        intent = escape(case["intent"])
        questions.append(
            f"""
<details{" open" if index == 0 else ""}>
  <summary>{question}</summary>
  <div class="contents">
    <p class="muted">{joined}</p>
    <p>{intent}</p>
    {content}
  </div>
</details>"""
        )
    return (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("__PACKET_SHA__", packet_sha)
        .replace("<!-- QUESTION_CARDS -->", "\n".join(questions))
    )


def prepare(args):
    packet = review_packet(args.release, args.rankings, QUERIES)
    args.output.mkdir(parents=True, exist_ok=True)
    packet_path = args.output / "review-packet.json"
    worksheet = args.output / "human-review.html"
    if packet_path.exists() or worksheet.exists():
        raise FileExistsError("Use a new output directory to preserve a frozen review worksheet.")
    content = json_bytes(packet)
    page = review_page(packet, digest(content))
    packet_path.write_bytes(content)
    worksheet.write_text(page, encoding="utf-8")
    return {
        "release_id": packet["release_id"],
        "questions": len(packet["cases"]),
        "unlabeled_pairs": sum(len(case["candidates"]) for case in packet["cases"]),
        "empty_queries_by_ranker": {
            mode: sum(not case["ranks"][mode] for case in packet["cases"]) for mode in MODES
        },
        "worksheet": str(worksheet.resolve()),
    }


def score(args):
    packet_bytes = args.packet.read_bytes()
    packet = json.loads(packet_bytes)
    submitted = read_json(args.judgments)
    reviewer = submitted.get("reviewer")
    if (
        submitted.get("packet_sha256") != digest(packet_bytes)
        or submitted.get("human_review") is not True
        or not isinstance(reviewer, str)
        or not reviewer.strip()
    ):
        raise ValueError("Provide a matching worksheet export confirmed by the human reviewer.")
    grades = submitted["judgments"]
    known = {item["pair"] for case in packet["cases"] for item in case["candidates"]}
    if not isinstance(grades, dict) or grades.keys() - known:
        raise ValueError("Unknown candidate pairs in the review.")
    labeled = {}
    for pair, entry in grades.items():
        if not isinstance(entry, dict):
            raise ValueError("Invalid judgment.")
        relevance, reason = entry.get("relevance"), entry.get("reason")
        if relevance is not None and (type(relevance) is not int or relevance not in (0, 1, 2)):
            raise ValueError(f"Invalid relevance label for {pair}.")
        if relevance is not None and isinstance(reason, str) and reason.strip():
            labeled[pair] = relevance
    if not labeled:
        raise ValueError("Enter at least one rating with an evidence reason before scoring.")
    assessed = {}
    for case in packet["cases"]:
        candidates = case["candidates"]
        if candidates and all(item["pair"] in labeled for item in candidates):
            assessed[case["id"]] = {item["id"]: labeled[item["pair"]] for item in candidates}
    rankers = {}
    for mode in MODES:
        reviewed = [
            [assessed[case["id"]][id_] for id_ in case["ranks"][mode]]
            for case in packet["cases"]
            if case["id"] in assessed
        ]
        quality = (
            {
                "queries_with_direct_in_top_3": sum(2 in labels[:3] for labels in reviewed),
                "direct_hits_in_top_3": sum(labels[:3].count(2) for labels in reviewed),
                "queries_with_useful_in_top_5": sum(
                    any(label >= 1 for label in labels) for labels in reviewed
                ),
            }
            if reviewed
            else None
        )
        rankers[mode] = {
            "empty_queries_out_of_all_cases": sum(
                not case["ranks"][mode] for case in packet["cases"]
            ),
            "relevance_counts_on_fully_judged_cases": quality,
        }
    return {
        "release_id": packet["release_id"],
        "reviewer": reviewer,
        "judgments_sha256": file_hash(args.judgments),
        "candidate_pairs": len(known),
        "human_judgments": len(labeled),
        "queries": len(packet["cases"]),
        "fully_judged_query_ids": list(assessed),
        "rankers": rankers,
        "scope": "Counts over fully judged frozen query pools. Empty-return counts cover all frozen queries.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_command = commands.add_parser("prepare")
    prepare_command.add_argument("--release", type=Path, default=PAGES)
    prepare_command.add_argument("--rankings", type=Path, default=ARTIFACTS / "rankings.json")
    prepare_command.add_argument("--output", type=Path, default=ARTIFACTS)
    score_command = commands.add_parser("score")
    score_command.add_argument("--packet", type=Path, default=ARTIFACTS / "review-packet.json")
    score_command.add_argument("--judgments", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args) if args.command == "prepare" else score(args)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
