from datetime import datetime

from pydantic import ValidationError

from .schemas import BBox, Compatibility, Constraints, EOCollection, Interval


def split_bbox(values) -> list[BBox]:
    if len(values) == 6:
        values = [values[i] for i in (0, 1, 3, 4)]
    bbox = Constraints(bbox=values).bbox
    if bbox is None:
        raise ValueError("bbox missing")
    w, s, e, n = bbox
    if w <= e:
        return [bbox]
    return [(w, s, 180, n), (-180, s, e, n)]


def bboxes(values, flags: list[str]) -> list[BBox] | None:
    result = []
    for value in values:
        try:
            result.extend(split_bbox(value))
        except (ValueError, TypeError):
            flags.append("invalid_bbox")
    if not result:
        flags.append("bbox_unknown")
    elif (-180, -90, 180, 90) in result:
        flags.append("global_bbox")
    return result or None


def interval(start, end, ongoing, flags: list[str]) -> Interval | None:
    if not start and not end:
        return None
    try:
        return Interval(start=start, end=end, ongoing=ongoing)
    except ValidationError:
        flags.append("invalid_temporal_interval")
        return None


def boxes_overlap(a: BBox, b: BBox) -> bool:
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def interval_overlap(value: Interval, start: datetime | None, end: datetime | None) -> bool | None:
    if (end and value.start and value.start > end) or (start and value.end and value.end < start):
        return False
    if (end and value.start is None) or (start and value.end is None and value.ongoing is not True):
        if value.start and start and start <= value.start and (not end or value.start <= end):
            return True
        if value.end and end and value.end <= end and (not start or start <= value.end):
            return True
        return None
    return True


def compatibility(doc: EOCollection, query: Constraints) -> Compatibility:
    checks = []
    if query.bbox:
        checks.append(
            any(boxes_overlap(a, b) for a in doc.bbox_parts for b in split_bbox(query.bbox))
            if doc.bbox_parts
            else None
        )
    if query.start or query.end:
        times = [interval_overlap(value, query.start, query.end) for value in doc.intervals]
        checks.append(True if True in times else None if not times or None in times else False)
    return (
        "not_requested"
        if not checks
        else "incompatible"
        if False in checks
        else "unknown"
        if None in checks
        else "compatible"
    )
