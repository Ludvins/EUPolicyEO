"""Searchable measurement vocabulary derived from archived catalogue field evidence."""

import re
from dataclasses import dataclass
from pathlib import Path

from .storage import file_hash, read_json


@dataclass(frozen=True)
class Measurement:
    label: str
    field: str
    evidence: str
    raw_sha256: str


_LABELS = {
    "chlorophyll-a concentration": r"chlorophyll[\s-]*a\b|\bchla[_-]?mean\b",
    "floating cyanobacteria": r"floating cyanobacteria",
    "water turbidity": r"\bturbidity\b",
    "suspended matter concentration": r"(total )?suspended matter",
    "land surface temperature": r"land surface temperature",
    "lake surface water temperature": r"lake surface water temperature",
    "leaf area index": r"leaf area index",
    "fraction of green vegetation cover": r"fraction of green vegetation cover|vegetation area fraction",
    "grassland mowing dates": r"grassland mowing dates",
    "grassland mowing events": r"grassland mowing events",
    "surface water extent": r"surface water extent|water bodies extent",
    "snow cover extent": r"snow cover extent|snow extent",
    "sea ice concentration": r"sea ice concentration",
    "ocean salinity": r"sea surface salinity|ocean salinity",
    "burned area": r"burn(?:ed|t) area",
}
_RULES = tuple((label, re.compile(expression, re.I)) for label, expression in _LABELS.items())
MEASUREMENT_TERMS = frozenset(_LABELS)


def catalogue_measurements(root: Path) -> dict[str, list[Measurement]]:
    """Use dedicated fields where the provider actually identifies a measured variable."""
    manifest = read_json(root / "manifest.json")
    if manifest["status"] != "success" or manifest["snapshot_id"] != root.name:
        raise ValueError("a completed source snapshot is required for measurement metadata")
    found: dict[str, dict[str, Measurement]] = {}
    for page in manifest["pages"]:
        source = page["source"]
        if source not in {"cdse", "cmr"}:
            continue
        name = page["path"]
        if not re.fullmatch(rf"{source}-[0-9]{{3}}\.raw", name):
            raise ValueError("unsafe archived catalogue path")
        path = root / name
        if path.is_symlink() or file_hash(path) != page["sha256"]:
            raise ValueError(f"catalogue checksum differs for {name}")
        payload = read_json(path)
        records = payload.get("collections", [payload]) if source == "cdse" else payload["items"]
        for item in records:
            if source == "cdse":
                identifier = item.get("id")
                values = [
                    ("STAC bands", str(band.get("description", "")).strip())
                    for band in (item.get("bands") or [])
                    if isinstance(band, dict)
                ]
            else:
                identifier = item.get("meta", {}).get("concept-id")
                values = [
                    ("CMR ScienceKeywords", str(leaf).strip())
                    for keyword in (item.get("umm", {}).get("ScienceKeywords") or [])
                    if isinstance(keyword, dict)
                    for leaf in (
                        keyword.get("VariableLevel1"),
                        keyword.get("VariableLevel2"),
                        keyword.get("VariableLevel3"),
                        keyword.get("DetailedVariable"),
                    )
                    if leaf
                ]
            if not identifier:
                continue
            entries = found.setdefault(f"{source}:{identifier}", {})
            for field, value in values:
                if (
                    not value
                    or len(value) > 300
                    or any(
                        token in value.lower()
                        for token in ("uncertainty", "quality flag", "confidence")
                    )
                ):
                    continue
                for label, pattern in _RULES:
                    if pattern.search(value):
                        entries.setdefault(label, Measurement(label, field, value, page["sha256"]))
    return {key: [rows[label] for label in sorted(rows)] for key, rows in found.items() if rows}


def measurement_labels(records: dict[str, list[Measurement]], identifier: str) -> list[str]:
    return [row.label for row in records.get(identifier, [])]
