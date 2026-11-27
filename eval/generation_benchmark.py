"""Run bounded Article 20 extraction and reporting-brief checks against local Ollama."""

import argparse
from pathlib import Path
from statistics import median
from time import perf_counter

from eupolicyeo.generation import (
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_URL,
    GenerationError,
    Ollama,
    assessment_sources,
    extract_legal,
    generate_brief,
    load_legal_sections,
)
from eupolicyeo.requirements import extract
from eupolicyeo.storage import file_hash, read_json, snapshot_dir, write_json

# Literal, source-derived checks on selected passages, frozen before the comparison.
LEGAL_CASES = {
    "1:b": [
        {
            "modality": ["obligation"],
            "actor": ["member states"],
            "action": ["monitor"],
            "scope": ["urban green space", "urban tree canopy cover"],
            "area": ["urban ecosystem areas"],
        }
    ],
    "1:g": [
        {
            "modality": ["obligation"],
            "actor": ["member states"],
            "scope": ["abundance", "diversity", "pollinator species"],
        }
    ],
    "3": [{"modality": ["obligation"], "deadline": ["18 august 2024"], "scope": ["(b)", "(f)"]}],
    "4": [
        {
            "modality": ["obligation"],
            "deadline": ["one year after", "delegated act"],
            "scope": ["(g)"],
        }
    ],
    "6": [
        {"modality": ["obligation"], "frequency": ["every six years"], "scope": ["(a)", "(b)"]},
        {"modality": ["obligation"], "frequency": ["every year"], "scope": ["pollinator species"]},
    ],
    "11:a": [
        {
            "modality": ["permission"],
            "actor": ["commission"],
            "action": ["specify"],
            "scope": ["agricultural ecosystems"],
        }
    ],
}
BRIEF_QUESTIONS = {
    "reporting": "What could support monitoring urban tree canopy and urban green space in Andalusia, and what remains unknown?",
    "outside_scope": "When does the train depart for Madrid Atocha?",
}


def score(rows, expected):
    return [
        any(
            all(
                all(token in (row[field] or "").casefold() for token in values)
                for field, values in case.items()
            )
            for row in rows
        )
        for case in expected
    ]


def model_fields(row):
    return {
        key: row[key]["quote"] if row[key] else None
        for key in ("actor", "action", "area", "scope", "deadline", "frequency")
    } | {"modality": row["modality"]}


def rule_fields(row):
    return {
        "actor": row.actor,
        "action": row.action,
        "area": row.area_text,
        "scope": row.observable,
        "deadline": row.deadline_text,
        "frequency": row.frequency_text,
        "modality": row.modality,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--assessment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--expected-digest", required=True)
    args = parser.parse_args()
    section_file = snapshot_dir(args.snapshot) / "sections.json"
    sections = load_legal_sections(args.snapshot)
    by_suffix = {section.id.split(":", 3)[3]: section for section in sections}
    if not set(LEGAL_CASES) <= by_suffix.keys():
        raise ValueError("The fixed benchmark requires the archived Article 20 passages")
    started = perf_counter()
    rule_rows = extract(sections)
    rule_seconds = round(perf_counter() - started, 4)
    matrix = read_json(args.assessment)
    if matrix["snapshot_id"] != args.snapshot:
        raise ValueError("The briefing assessment and legal extraction must share a snapshot")
    comparisons = []
    timings = []
    brief_runs = {}
    with Ollama(
        model=args.model, url=args.ollama_url, expected_digest=args.expected_digest
    ) as engine:
        for suffix, expected in LEGAL_CASES.items():
            section = by_suffix[suffix]
            rule = [rule_fields(row) for row in rule_rows if row.section_id == section.id]
            record = {
                "section_id": section.id,
                "expected": expected,
                "rules": {"outputs": rule, "checks_passed": score(rule, expected)},
            }
            run_started = perf_counter()
            try:
                output = extract_legal(sections, [section.id], engine)["runs"][0]
                timings.append(output["timings"]["wall_seconds"])
                result = [model_fields(row) for row in output["requirements"]]
                record["llm"] = {**output, "checks_passed": score(result, expected)}
            except GenerationError as exc:
                record["llm"] = {
                    "error": str(exc),
                    "wall_seconds": round(perf_counter() - run_started, 4),
                    "checks_passed": [False] * len(expected),
                }
            comparisons.append(record)
            print(section.id, record["llm"]["checks_passed"], flush=True)

        sources = assessment_sources(matrix)
        for name, question in BRIEF_QUESTIONS.items():
            try:
                brief_runs[name] = generate_brief(question, sources, engine)
            except GenerationError as exc:
                brief_runs[name] = {"error": str(exc)}
            print(name, brief_runs[name].get("status", "error"), flush=True)

        report = {
            "snapshot_id": args.snapshot,
            "input_sha256": {
                "legal_sections": file_hash(section_file),
                "assessment": file_hash(args.assessment),
            },
            "protocol": "article20-local-generation-checks-v1",
            "model": engine.identity,
            "scope": "Fixed diagnostics on legal passages and a single reporting scenario. This does not estimate general legal extraction or answer accuracy.",
            "legal": {
                "passages": len(LEGAL_CASES),
                "checks": sum(map(len, LEGAL_CASES.values())),
                "rules_checks_passed": sum(sum(r["rules"]["checks_passed"]) for r in comparisons),
                "llm_checks_passed": sum(sum(r["llm"]["checks_passed"]) for r in comparisons),
                "validated_runs": len(timings),
                "rule_extraction_all_article_wall_seconds": rule_seconds,
                "validated_llm_median_wall_seconds": median(timings) if timings else None,
                "comparisons": comparisons,
            },
            "briefs": brief_runs,
        }
    write_json(args.output, report)


if __name__ == "__main__":
    main()
