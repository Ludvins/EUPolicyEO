"""Bounded metadata inventory kept separate from the collection corpora."""

import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp
from time import monotonic, perf_counter
from urllib.parse import quote, urljoin

import httpx

from .geometry import bboxes, compatibility, split_bbox
from .normalization import provenance
from .schemas import Constraints, EOCollection, EOGranule
from .settings import Config, artifacts
from .sources import Fetcher
from .storage import digest, json_bytes, read_json, snapshot_dir, write_json, write_table

STAC_SEARCH = "https://stac.dataspace.copernicus.eu/v1/search"
CMR_GRANULES = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"


def cloud(value, flags):
    if value is None:
        return None
    if not isinstance(value, (int, float)) or not 0 <= value <= 100:
        flags.append("invalid_cloud_cover")
        return None
    return value


def bounds_for_polygon(geometry: dict, flags: list[str]):
    values = []
    for polygon in geometry.get("GPolygons", []):
        points = polygon.get("Boundary", {}).get("Points", [])
        if not points:
            continue
        lons = [point["Longitude"] for point in points]
        lats = [point["Latitude"] for point in points]
        if max(lons) - min(lons) > 180:
            flags.append("antimeridian_polygon_unsupported")
        else:
            values.append([min(lons), min(lats), max(lons), max(lats)])
            flags.append("polygon_bbox_approximation")
    for r in geometry.get("BoundingRectangles", []):
        values.append(
            [
                r.get(key)
                for key in (
                    "WestBoundingCoordinate",
                    "SouthBoundingCoordinate",
                    "EastBoundingCoordinate",
                    "NorthBoundingCoordinate",
                )
            ]
        )
    return values


def normalize_granule(record, page, snap, collection_id) -> EOGranule:
    flags = []
    if page.source == "cdse":
        if collection_id != f"cdse:{record['collection']}":
            raise ValueError("STAC item does not belong to requested collection")
        p = record["properties"]
        item = record["id"]
        url = (
            "https://stac.dataspace.copernicus.eu/v1/collections/"
            f"{quote(record['collection'], safe='')}/items/{quote(item, safe='')}"
        )
        values = [record["bbox"]] if record.get("bbox") is not None else []
        start = p.get("start_datetime") or p.get("datetime")
        end = p.get("end_datetime") or p.get("datetime")
        cover = p.get("eo:cloud_cover")
        revision = None
        if record.get("geometry"):
            flags.append("polygon_bbox_approximation")
        identifier = f"{collection_id}:{item}"
    else:
        meta, umm = record["meta"], record["umm"]
        if collection_id != f"cmr:{meta['collection-concept-id']}":
            raise ValueError("CMR granule does not belong to requested collection")
        item = meta["concept-id"]
        geometry = (
            umm.get("SpatialExtent", {}).get("HorizontalSpatialDomain", {}).get("Geometry", {})
        )
        values = bounds_for_polygon(geometry, flags)
        time = umm.get("TemporalExtent", {})
        dates = time.get("RangeDateTime", {})
        start = dates.get("BeginningDateTime") or time.get("SingleDateTime")
        end = dates.get("EndingDateTime") or time.get("SingleDateTime")
        url = f"{CMR_GRANULES}?concept_id={quote(item, safe='')}"
        cover = umm.get("CloudCover")
        revision = str(meta["revision-id"])
        identifier = f"cmr:{item}"
    if not start or not end:
        flags.append("temporal_unknown")
    geometry = bboxes(values, flags)
    cover = cloud(cover, flags)
    return EOGranule(
        id=identifier,
        collection_id=collection_id,
        bbox_parts=geometry,
        temporal_start=start,
        temporal_end=end,
        cloud_cover_percent=cover,
        metadata_quality_flags=list(dict.fromkeys(flags)),
        provenance=provenance(page, snap, item, url, revision),
    )


def stac_pages(fetch: Fetcher, identifier: str, bbox, start: str, end: str, pages: int, limit: int):
    url, method = STAC_SEARCH, "POST"
    search = {
        "collections": [identifier],
        "bbox": list(bbox),
        "datetime": f"{start}/{end}",
        "limit": limit,
    }
    body = search
    seen = set()
    for page_number in range(pages):
        key = digest(json_bytes([method, url, body]))
        if key in seen:
            raise ValueError("repeated STAC item continuation")
        seen.add(key)
        try:
            path, _ = fetch.fetch("cdse", url, method=method, body=body)
        except httpx.HTTPStatusError as exc:
            if page_number != 0 or exc.response.status_code not in {405, 501}:
                raise
            path, _ = fetch.fetch(
                "cdse",
                STAC_SEARCH,
                params={
                    "collections": identifier,
                    "bbox": ",".join(map(str, bbox)),
                    "datetime": f"{start}/{end}",
                    "limit": limit,
                },
            )
        response = read_json(path)
        yield fetch.pages[-1], response["features"]
        link = next((link for link in response["links"] if link["rel"] == "next"), None)
        if not link or not response["features"]:
            break
        url = urljoin(url, link["href"])
        method = link.get("method", "GET")
        if method not in {"GET", "POST"}:
            raise ValueError("unsupported STAC next method")
        body = (
            None
            if method == "GET"
            else ({**search, **link.get("body", {})} if link.get("merge") else link.get("body"))
        )


def cmr_pages(fetch: Fetcher, identifier: str, bbox, start: str, end: str, pages: int, limit: int):
    params = {
        "collection_concept_id": identifier,
        "bounding_box": ",".join(map(str, bbox)),
        "temporal": f"{start},{end}",
        "page_size": limit,
    }
    headers = {"Accept": "application/vnd.nasa.cmr.umm_results+json;version=1.6.7"}
    seen = set()
    acquired = 0
    for _ in range(pages):
        path, response_headers = fetch.fetch("cmr", CMR_GRANULES, headers, params)
        items = read_json(path)["items"]
        yield fetch.pages[-1], items
        acquired += len(items)
        token = response_headers.get("CMR-Search-After")
        hits = fetch.pages[-1].hits
        if not token or not items or (hits is not None and acquired >= hits):
            break
        if token in seen:
            raise ValueError("repeated CMR granule continuation")
        seen.add(token)
        headers["CMR-Search-After"] = token


def inventory(
    snapshot: str, collection_ids: list[str], bounds: Constraints, pages: int, limit: int
):
    if not bounds.bbox or not bounds.start or not bounds.end or not collection_ids:
        raise ValueError("inventory requires bbox, start, end and collections")
    if not 1 <= pages <= 100 or not 1 <= limit <= 100 or len(collection_ids) > 8:
        raise ValueError("inventory exceeds paging budget")
    sroot = snapshot_dir(snapshot)
    source_manifest = read_json(sroot / "manifest.json")
    if source_manifest["status"] != "success":
        raise ValueError("granule inventory requires successful collection snapshot")
    lookup = {r["id"]: r for r in read_json(sroot / "collections.json")}
    if any(key not in lookup for key in collection_ids):
        raise ValueError("granule query collection ID was not discovered in the snapshot")
    root = artifacts() / "granules" / snapshot
    root.mkdir(parents=True, exist_ok=True)
    stage = Path(mkdtemp(dir=root, prefix=".inventory-"))
    config = Config.model_validate(source_manifest["config"])
    counts = {key: Counter() for key in collection_ids}
    unique = {}
    error = None
    started = perf_counter()
    with httpx.Client(headers={"User-Agent": "EUPolicyEO/0.1 metadata research demo"}) as client:
        fetch = Fetcher(stage, config, client)
        try:
            for collection_id in collection_ids:
                source, identifier = collection_id.split(":", 1)
                paging = stac_pages if source == "cdse" else cmr_pages
                fetch.deadline = monotonic() + config.source_budget_seconds
                seen_pages: set[str] = set()
                for box in split_bbox(bounds.bbox):
                    for page, records in paging(
                        fetch,
                        identifier,
                        box,
                        bounds.start.isoformat(),
                        bounds.end.isoformat(),
                        pages,
                        limit,
                    ):
                        counts[collection_id]["pages"] += 1
                        if page.hits is not None:
                            counts[collection_id]["last_reported_hits"] = page.hits
                        page_ids = [
                            r["id"] if source == "cdse" else r["meta"]["concept-id"]
                            for r in records
                        ]
                        page_key = digest(json_bytes([box, page_ids]))
                        if page_ids and page_key in seen_pages:
                            raise ValueError("provider returned repeated item page")
                        seen_pages.add(page_key)
                        for record in records:
                            counts[collection_id]["fetched"] += 1
                            try:
                                row = normalize_granule(record, page, snapshot, collection_id)
                            except (ValueError, TypeError, KeyError):
                                counts[collection_id]["rejected"] += 1
                                continue
                            if old := unique.get(row.id):
                                counts[collection_id]["duplicate"] += 1
                                if source != "cmr" or int(row.provenance.revision) <= int(
                                    old.provenance.revision
                                ):
                                    continue
                            unique[row.id] = row
        except (ValueError, TypeError, OSError, KeyError, httpx.HTTPError) as exc:
            error = f"{type(exc).__name__}: {exc}"
    rows = sorted(unique.values(), key=lambda row: row.id)
    for row in rows:
        counts[row.collection_id]["accepted"] += 1
    scope = {
        "collections": collection_ids,
        "bounds": bounds.model_dump(mode="json"),
        "max_pages_per_box_collection": pages,
        "page_size": limit,
    }
    ident = digest(json_bytes([snapshot, scope, [p.sha256 for p in fetch.pages], error]))[:24]
    report = {
        "inventory_id": ident,
        "snapshot_id": snapshot,
        "status": "partial" if error else "success",
        "error": error,
        "at": datetime.now(UTC).isoformat(),
        "scope": scope,
        "elapsed_seconds": round(perf_counter() - started, 4),
        "retries": fetch.retries,
        "bytes": sum(p.size for p in fetch.pages),
        "counts": {key: dict(c) for key, c in counts.items()},
        "raw_pages": [page.model_dump(mode="json") for page in fetch.pages],
    }
    write_json(stage / "granules.json", [row.model_dump(mode="json") for row in rows])
    if rows:
        write_table(stage / "granules.parquet", rows)
    write_json(stage / "manifest.json", report)
    destination = root / ident
    if destination.exists():
        shutil.rmtree(stage)
    else:
        stage.rename(destination)
    if not error:
        write_json(root / "current.json", {"inventory_id": ident})
    return report


def availability(snapshot: str, collection: EOCollection, query: Constraints) -> dict:
    root = artifacts() / "granules" / snapshot
    pointer = root / "current.json"
    if not pointer.is_file():
        return {
            "status": "not_scanned",
            "collection_id": collection.id,
            "observed_compatible": None,
        }
    ident = read_json(pointer)["inventory_id"]
    directory = root / ident
    report = read_json(directory / "manifest.json")
    if report["status"] != "success" or collection.id not in report["scope"]["collections"]:
        return {
            "status": "not_scanned",
            "collection_id": collection.id,
            "observed_compatible": None,
        }
    matches = Counter()
    for row in read_json(directory / "granules.json"):
        if row["collection_id"] != collection.id:
            continue
        start, end = row["temporal_start"], row["temporal_end"]
        extent = collection.model_copy(update={"bbox_parts": row["bbox_parts"], "intervals": []})
        if start or end:
            from .schemas import Interval

            extent.intervals.append(Interval(start=start, end=end))
        matches[compatibility(extent, query)] += 1
    return {
        "status": "bounded_inventory",
        "inventory_id": ident,
        "collection_id": collection.id,
        "observed_compatible": matches["compatible"] + matches["not_requested"],
        "unknown": matches["unknown"],
        "incompatible": matches["incompatible"],
        "scan_scope": report["scope"],
        "scan_counts": report["counts"][collection.id],
        "limitation": "Counts describe observations in the bounded local metadata inventory.",
    }
