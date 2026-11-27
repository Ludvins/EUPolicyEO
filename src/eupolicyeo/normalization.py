import csv
import io
import re
from collections import Counter
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit
from zipfile import ZipFile, is_zipfile

from lxml import html

from .geometry import bboxes, interval
from .schemas import (
    EOCollection,
    LegalSection,
    Provenance,
    RawPage,
    ResearchProject,
    SnapshotManifest,
)
from .settings import Config
from .storage import file_hash, read_json, snapshot_dir, write_json, write_table

ARTICLE = re.compile(r"^Article (\d+[a-z]?)$")
PARAGRAPH = re.compile(r"^\s*(\d+)\.\s+")
POINT = re.compile(r"^\(([a-z]+|[ivx]+)\)$")
NULL = {"", "null", "n/a", "none"}


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value if value.lower() not in NULL else None


def text(node) -> str:
    return clean("".join(node.itertext())) or ""


def provenance(
    page: RawPage, snapshot: str, source_id: str, url: str, revision: str | None = None
) -> Provenance:
    return Provenance(
        source=page.source,
        source_id=source_id,
        source_url=url,
        retrieved_at=page.retrieved_at,
        raw_sha256=page.sha256,
        snapshot_id=snapshot,
        revision=revision or page.revision,
    )


def legal_sections(path: Path, cfg: Config, page: RawPage, snapshot: str) -> list[LegalSection]:
    tree = html.fromstring(
        path.read_bytes(),
        parser=html.HTMLParser(
            encoding="utf-8",
            no_network=True,
            huge_tree=False,
        ),
    )
    serial = f"{cfg.celex[1:5]}/{int(cfg.celex[6:])}"
    titles = tree.xpath("//p[@class='oj-doc-ti']/text()")
    if not any(serial in part for part in titles):
        raise ValueError("CELLAR publication identity did not match CELEX")
    if [text(node) for node in tree.xpath("//p[@class='oj-hd-lg']")] != ["EN"]:
        raise ValueError("CELLAR language marker did not match English")
    candidate = tree.xpath(
        "//div[@id=$id and contains(@class,'eli-subdivision')]", id=f"art_{cfg.article}"
    )
    if len(candidate) != 1:
        raise ValueError(f"expected one CELLAR Article {cfg.article} subdivision")
    article_node = candidate[0]
    label = article_node.xpath("./p[@class='oj-ti-art']")
    match = ARTICLE.fullmatch(text(label[0])) if label else None
    if not match or match.group(1) != cfg.article:
        raise ValueError("malformed operative article heading")
    heading = article_node.xpath("./div[contains(@class,'eli-title')]")
    base = f"{cfg.celex}:{cfg.language}:{cfg.article}"
    url = f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{cfg.celex}#art_{cfg.article}"
    prov = provenance(page, snapshot, cfg.celex, url)
    sections = []

    def add(node, content, paragraph=None, point=None, parent=None):
        id_ = ":".join(part for part in [base, paragraph, point] if part is not None)
        if content:
            sections.append(
                LegalSection(
                    id=id_,
                    celex=cfg.celex,
                    language=cfg.language,
                    article=cfg.article,
                    paragraph=paragraph,
                    point=point,
                    parent_id=parent,
                    title=text(heading[0]) if heading else None,
                    text=content,
                    raw_xpath=tree.getroottree().getpath(node),
                    provenance=prov,
                )
            )
        return id_

    def points(node, paragraph, prefix, parent):
        for table in node.xpath("./table"):
            cells = table.xpath("./tbody/tr/td | ./tr/td")
            if len(cells) != 2 or not (match := POINT.fullmatch(text(cells[0]))):
                continue
            point = ".".join(filter(None, [prefix, match.group(1)]))
            pid = add(
                cells[1], " ".join(map(text, cells[1].xpath("./p"))), paragraph, point, parent
            )
            points(cells[1], paragraph, point, pid)

    add(article_node, " ".join(map(text, article_node.xpath("./p[@class='oj-normal']"))))
    for div in article_node.xpath("./div[./p[@class='oj-normal']]"):
        body = " ".join(map(text, div.xpath("./p")))
        number = PARAGRAPH.match(body)
        if number:
            parent = add(div, body[number.end() :], number.group(1))
            points(div, number.group(1), None, parent)
    if not sections or len({section.id for section in sections}) != len(sections):
        raise ValueError("no unique operative sections found")
    return sections


@contextmanager
def project_stream(path: Path):
    if not is_zipfile(path):
        with path.open(encoding="utf-8-sig", newline="") as stream:
            yield stream
        return
    with ZipFile(path) as archive:
        items = archive.infolist()
        if any(
            PurePosixPath(item.filename).name != item.filename
            or "\\" in item.filename
            or ":" in item.filename
            for item in items
        ):
            raise ValueError("unexpected non-flat CORDIS ZIP member")
        matches = [item for item in items if item.filename == "project.csv"]
        if len(matches) != 1 or matches[0].file_size > 180_000_000:
            raise ValueError("expected exactly one bounded CORDIS project.csv")
        with (
            archive.open(matches[0]) as member,
            io.TextIOWrapper(member, encoding="utf-8-sig", newline="") as stream,
        ):
            yield stream


def projects(path: Path, cfg: Config, page: RawPage, snapshot: str, counts: Counter):
    output: dict[str, ResearchProject] = {}
    with project_stream(path) as stream:
        header = stream.readline()
        dialect = csv.Sniffer().sniff(header, delimiters=";,\t")
        from itertools import chain

        reader = csv.DictReader(chain([header], stream), dialect=dialect)
        required = {"id", "title", "objective"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(
                f"CORDIS columns missing: {sorted(required - set(reader.fieldnames or []))}"
            )
        for row in reader:
            counts["parsed"] += 1
            identifier, title = clean(row.get("id")), clean(row.get("title"))
            if (
                identifier is None
                or not identifier.isascii()
                or not identifier.isdigit()
                or not title
            ):
                counts["rejected"] += 1
                continue
            if identifier in output:
                counts["duplicate"] += 1
                continue
            if len(output) >= cfg.cordis_limit:
                counts["excluded_at_cap"] += 1
                continue
            objective = clean(row.get("objective"))
            output[identifier] = ResearchProject(
                id=f"cordis:{identifier}",
                title=title,
                description=objective,
                acronym=clean(row.get("acronym")),
                programme=clean(row.get("frameworkProgramme")),
                start_date=clean(row.get("startDate")),
                end_date=clean(row.get("endDate")),
                keywords=[x.strip() for x in (row.get("keywords") or "").split(";") if x.strip()],
                topics=[x.strip() for x in (row.get("topics") or "").split(";") if x.strip()],
                provider="CORDIS",
                metadata_quality_flags=[] if objective else ["objective_unknown"],
                provenance=provenance(
                    page, snapshot, identifier, f"https://cordis.europa.eu/project/id/{identifier}"
                ),
            )
    return list(output.values())


def secure_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and not (parsed.username or parsed.password)
    )


def strings(values):
    return list(
        dict.fromkeys(value for value in values if isinstance(value, str) and value.strip())
    )


def collection(
    page: RawPage,
    snap: str,
    identifier: str,
    title: str,
    description: str | None,
    url: str,
    flags: list[str],
    boxes,
    intervals,
    revision=None,
    **fields,
) -> EOCollection:
    if not identifier or not clean(title):
        raise ValueError("collection missing identifier or title")
    parts = bboxes(boxes, flags)
    intervals = [value for value in intervals if value]
    if not intervals:
        flags.append("temporal_unknown")
    if not description:
        flags.append("description_unknown")
    if not fields.get("spatial_resolution_m"):
        flags.append("resolution_unknown")
    # Aggregate bounds are display-only. Filtering uses individual source intervals.
    return EOCollection(
        id=f"{page.source}:{identifier}",
        title=clean(title),
        description=clean(description),
        provenance=provenance(page, snap, identifier, url, revision),
        bbox_parts=parts,
        intervals=intervals,
        temporal_start=min((i.start for i in intervals if i.start), default=None),
        temporal_end=max((i.end for i in intervals), default=None)
        if intervals and all(i.end for i in intervals)
        else None,
        ongoing=True
        if any(i.ongoing is True for i in intervals)
        else False
        if intervals and all(i.ongoing is False for i in intervals)
        else None,
        metadata_quality_flags=list(dict.fromkeys(flags)),
        **fields,
    )


def stac(raw: dict, page: RawPage, snap: str) -> EOCollection:
    identifier = raw["id"]
    extent, summary = raw.get("extent", {}), raw.get("summaries", {})
    flags = []
    times = [
        interval(start, end, True if start and not end else None, flags)
        for start, end in extent.get("temporal", {}).get("interval", [])
    ]
    links = {
        link["rel"]: link["href"] for link in raw.get("links", []) if secure_url(link.get("href"))
    }
    gsds = summary.get("gsd")
    resolution = (
        gsds[0]
        if isinstance(gsds, list)
        and len(gsds) == 1
        and isinstance(gsds[0], (int, float))
        and gsds[0] > 0
        else None
    )
    return collection(
        page,
        snap,
        identifier,
        raw.get("title") or identifier,
        raw.get("description"),
        f"https://stac.dataspace.copernicus.eu/v1/collections/{quote(identifier, safe='')}",
        flags,
        extent.get("spatial", {}).get("bbox", []),
        times,
        platform=strings(summary.get("platform", [])),
        instrument=strings(summary.get("instruments", [])),
        keywords=strings(raw.get("keywords", [])),
        provider="CDSE",
        spatial_resolution_m=resolution,
        access_urls=[links[key] for key in ("self", "license") if key in links],
        license=raw.get("license"),
    )


def umm(raw: dict, page: RawPage, snap: str) -> EOCollection:
    meta, body = raw["meta"], raw["umm"]
    identifier = meta["concept-id"]
    geometry = body.get("SpatialExtent", {}).get("HorizontalSpatialDomain", {}).get("Geometry", {})
    rects = [
        [
            r.get(k)
            for k in (
                "WestBoundingCoordinate",
                "SouthBoundingCoordinate",
                "EastBoundingCoordinate",
                "NorthBoundingCoordinate",
            )
        ]
        for r in geometry.get("BoundingRectangles", [])
    ]
    flags = ["polygon_coverage_unsupported"] if geometry.get("GPolygons") else []
    times = []
    for spec in body.get("TemporalExtents", []):
        ongoing = spec.get("EndsAtPresentFlag")
        for value in spec.get("RangeDateTimes", []):
            times.append(
                interval(
                    value.get("BeginningDateTime"), value.get("EndingDateTime"), ongoing, flags
                )
            )
        for value in spec.get("SingleDateTimes", []):
            times.append(interval(value, value, False, flags))
        if spec.get("PeriodicDateTimes"):
            flags.append("periodic_extent_unsupported")
    urls = [
        u["URL"]
        for u in body.get("RelatedUrls", [])
        if u.get("Type") == "DATA SET LANDING PAGE" and secure_url(u.get("URL"))
    ]
    fallback = f"https://cmr.earthdata.nasa.gov/search/collections.umm_json?concept_id={quote(identifier, safe='')}"
    platforms = body.get("Platforms", [])
    return collection(
        page,
        snap,
        identifier,
        body["EntryTitle"],
        body.get("Abstract"),
        urls[0] if urls else fallback,
        flags,
        rects,
        times,
        revision=str(meta["revision-id"]),
        provider=meta.get("provider-id"),
        access_urls=urls,
        platform=strings(p.get("ShortName") for p in platforms),
        instrument=strings(i.get("ShortName") for p in platforms for i in p.get("Instruments", [])),
        keywords=strings(v for entry in body.get("ScienceKeywords", []) for v in entry.values()),
        use_constraints=bool(body.get("UseConstraints")),
    )


def normalize(snapshot: str) -> dict:
    from time import perf_counter

    started = perf_counter()
    root = snapshot_dir(snapshot)
    manifest = SnapshotManifest.model_validate(read_json(root / "manifest.json"))
    if manifest.status != "success" or manifest.snapshot_id != snapshot:
        raise ValueError("normalization requires a successful matching snapshot")
    cfg = Config.model_validate(manifest.config)
    counts = {source: Counter() for source in ("cellar", "cordis", "cdse", "cmr")}
    collections = {}
    output = {}
    for page in manifest.pages:
        raw = root / page.path
        if raw.parent != root or file_hash(raw) != page.sha256:
            raise ValueError("snapshot raw hash mismatch")
        count = counts[page.source]
        if page.source == "cellar":
            output["sections"] = legal_sections(raw, cfg, page, snapshot)
            count["parsed"] += len(output["sections"])
        elif page.source == "cordis":
            output["projects"] = projects(raw, cfg, page, snapshot, count)
        else:
            key, convert = ("collections", stac) if page.source == "cdse" else ("items", umm)
            payload = read_json(raw)
            records = [payload] if page.source == "cdse" and "id" in payload else payload[key]
            for record in records:
                count["parsed"] += 1
                try:
                    doc = convert(record, page, snapshot)
                except (ValueError, KeyError, TypeError):
                    count["rejected"] += 1
                    continue
                if old := collections.get(doc.id):
                    count["duplicate"] += 1
                    if page.source != "cmr" or int(old.provenance.revision) >= int(
                        doc.provenance.revision
                    ):
                        continue
                collections[doc.id] = doc
    output["collections"] = list(collections.values())
    if set(output) != {"projects", "sections", "collections"}:
        raise ValueError("canonical tables missing source")
    for rows in output.values():
        for row in rows:
            counts[row.provenance.source]["accepted"] += 1
    if any(not count["accepted"] for count in counts.values()):
        raise ValueError("one or more required sources have no accepted records")
    for name, rows in output.items():
        rows.sort(key=lambda row: row.id)
        write_json(root / f"{name}.json", [r.model_dump(mode="json") for r in rows])
        write_table(root / f"{name}.parquet", rows)
    report = {
        "snapshot_id": snapshot,
        "created_at": manifest.created_at.isoformat(),
        "sources": {source: dict(count) for source, count in counts.items()},
        "elapsed_seconds": round(perf_counter() - started, 4),
        "canonical_bytes": sum((root / f"{name}.parquet").stat().st_size for name in output),
    }
    write_json(root / "normalization.json", report)
    return report
