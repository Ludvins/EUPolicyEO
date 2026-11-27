"""Retrieve and archive the bounded CDSE evidence used by the Andalusia assessment."""

import argparse
from datetime import UTC, datetime
from pathlib import Path
from time import sleep

import httpx

from eupolicyeo.geometry import boxes_overlap, split_bbox
from eupolicyeo.storage import digest, write_json
from eupolicyeo.suitability import DEFAULT_SCENARIO, PRODUCTS

ROOT = "https://stac.dataspace.copernicus.eu/v1/collections"


def fetch(client, url, raw_path, params=None):
    response = client.get(url, params=params)
    raw_path.write_bytes(response.content)
    data = response.json()
    return data, {
        "url": str(response.url),
        "http_status": response.status_code,
        "sha256": digest(response.content),
        "bytes": len(response.content),
    }


def sample(data, collection, year, bbox):
    items = []
    for feature in data["features"]:
        bounds = feature.get("bbox")
        props = feature["properties"]
        start = props.get("start_datetime") or props.get("datetime")
        if (
            feature.get("collection") == collection
            and isinstance(start, str)
            and start.startswith(f"{year}-")
            and bounds is not None
            and any(boxes_overlap(bound, bbox) for bound in split_bbox(bounds))
        ):
            items.append({"id": feature["id"], "bbox": bounds})
    return items


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/article20-assessment/provider")
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    scenario = DEFAULT_SCENARIO
    collection = PRODUCTS[0].code
    report = {
        "captured_at": datetime.now(UTC).isoformat(),
        "collection_id": f"cdse:{collection}",
        "bbox": scenario.bbox,
        "checked_collections": [],
        "yearly_samples": [],
    }
    with httpx.Client(timeout=20) as client:
        for product in PRODUCTS:
            data, e = fetch(client, f"{ROOT}/{product.code}", args.output / f"{product.code}.json")
            report["checked_collections"].append(
                {**e, "id": data.get("id"), "title": data.get("title")}
            )
            sleep(0.45)
        for year in range(scenario.start_year, scenario.end_year + 1):
            data, e = fetch(
                client,
                f"{ROOT}/{collection}/items",
                args.output / f"canopy-{year}.json",
                {
                    "bbox": ",".join(map(str, scenario.bbox)),
                    "datetime": f"{year}-01-01T00:00:00Z/{year}-12-31T23:59:59Z",
                    "limit": 3,
                },
            )
            items = sample(data, collection, year, scenario.bbox) if e["http_status"] == 200 else []
            report["yearly_samples"].append({**e, "year": year, "items": items})
            sleep(0.45)
    write_json(args.output / "observation-samples.json", report)
    for evidence in report["checked_collections"]:
        print(evidence["http_status"], evidence["id"], evidence["sha256"])
    for evidence in report["yearly_samples"]:
        print(evidence["year"], evidence["http_status"], len(evidence["items"]), evidence["sha256"])


if __name__ == "__main__":
    main()
