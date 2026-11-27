"""Review fixed, source-backed identity cases with the optional local model."""

import argparse
from pathlib import Path
from time import perf_counter

from eupolicyeo.entity_resolution import inspect_pair, llm_adjudicator
from eupolicyeo.generation import Ollama
from eupolicyeo.storage import write_json

SNAPSHOT = "5ed3d4d678b09a79ad422601"
CASES = (
    (
        "cdse:clms_fcover_global_300m_10daily_v1_cog",
        "cdse:clms_fcover_global_300m_10daily_v1_nc",
        "same_delivery_family",
        "The catalogue declares one dataset DOI, one product page, the same extent and two file formats.",
    ),
    (
        "cdse:clms_lai_global_300m_10daily_v1_cog",
        "cdse:clms_lai_global_300m_10daily_v1_nc",
        "same_delivery_family",
        "Both formats use dataset DOI 10.2909/219fdc9f-616b-444b-a495-198f527b4722.",
    ),
    (
        "cdse:clms_fcover_global_300m_10daily_v1_nc",
        "cdse:clms_fcover_global_300m_10daily_v2_nc",
        "different_variants",
        "The catalogue declares different editions and dataset DOIs at the same nominal resolution.",
    ),
    (
        "cdse:clms_wsi_high-resolution-water-layer_europe_laea_10m_3yearly_v1",
        "cdse:clms_wsi_high-resolution-water-layer_europe_utm_10m_3yearly_v1",
        "different_variants",
        "The common DOI covers distinct LAEA and UTM projection variants.",
    ),
    (
        "cdse:clms_lwq-reproc_global_300m_10daily_v1_cog",
        "cdse:clms_lwq-reproc_global_300m_10daily_v1_nc",
        "insufficient_evidence",
        "The archived listings omit a dataset DOI and official product-page link. Format labels and a similar ID alone do not confirm equivalence.",
    ),
    (
        "cdse:sentinel-2-l2a",
        "cmr:C3246894861-LPCLOUD",
        "different_variants",
        "The CDSE collection distributes Sentinel-2 Level-2A imagery. The CMR collection distributes 30 m vegetation indices derived from harmonized Sentinel-2 observations.",
    ),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--case", type=int, choices=range(1, len(CASES) + 1), action="append")
    args = parser.parse_args()

    records = []
    with Ollama(model=args.model, url=args.url, expected_digest=args.digest) as engine:
        adjudicate = llm_adjudicator(engine)
        for index in args.case or range(1, len(CASES) + 1):
            left, right, expected, evidence = CASES[index - 1]
            pair = inspect_pair(SNAPSHOT, left, right)
            started = perf_counter()
            try:
                result = adjudicate(pair)
            except (ValueError, RuntimeError) as error:
                result = {"error_type": type(error).__name__, "error": str(error)}
            observed = result.get("advice", {}).get("decision")
            records.append(
                {
                    "id": pair["id"],
                    "left": pair["left"],
                    "right": pair["right"],
                    "reference": expected,
                    "reference_evidence": evidence,
                    "baseline_decision": pair["decision"],
                    "observed": observed,
                    "seconds": round(perf_counter() - started, 4),
                    "result": result,
                }
            )
            print(f"{left} / {right}: {observed or 'review failed'}", flush=True)
        report = {
            "snapshot_id": SNAPSHOT,
            "reference_type": "Diagnostic cases checked against archived source fields",
            "model": engine.identity,
            "cases": len(records),
            "valid": sum(row["observed"] is not None for row in records),
            "agreed": sum(row["observed"] == row["reference"] for row in records),
            "records": records,
        }
        write_json(args.output, report)
    print({key: report[key] for key in ("cases", "valid", "agreed")})


if __name__ == "__main__":
    main()
