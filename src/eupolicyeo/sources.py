import random
import re
import shutil
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from tempfile import mkdtemp
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from .schemas import RawPage, SnapshotManifest, Source
from .settings import Config, artifacts
from .storage import digest, file_hash, json_bytes, write_json

CELLAR = "https://publications.europa.eu/resource/celex/"
CORDIS = "https://cordis.europa.eu/data/cordis-HORIZONprojects-csv.zip"
CDSE = "https://stac.dataspace.copernicus.eu/v1/collections"
CMR = "https://cmr.earthdata.nasa.gov/search/collections.umm_json"
TERMS = {
    "cellar": "https://eur-lex.europa.eu/content/help/data-reuse/reuse-contents-eurlex-details.html",
    "cordis": "https://cordis.europa.eu/about/legal",
    "cdse": "https://dataspace.copernicus.eu/terms-and-conditions",
    "cmr": "https://www.earthdata.nasa.gov/engage/open-data-services-software-policies",
}
HOST = {
    name: urlsplit(url).hostname
    for name, url in zip(TERMS, (CELLAR, CORDIS, CDSE, CMR), strict=True)
}
MAX_BYTES = {"cellar": 6_000_000, "cordis": 75_000_000, "cdse": 12_000_000, "cmr": 12_000_000}
RETRY_STATUS = {429, 500, 502, 503, 504}


def allowed(source: Source, url: str) -> str:
    parts = urlsplit(url)
    if (
        source == "cellar"
        and parts.scheme == "http"
        and parts.hostname == HOST[source]
        and parts.path.startswith("/resource/cellar/")
    ):
        parts = parts._replace(scheme="https")
    if (
        parts.scheme != "https"
        or parts.netloc != HOST[source]
        or parts.fragment
        or not parts.path.startswith(
            {
                "cellar": "/resource/",
                "cordis": "/data/",
                "cdse": "/v1/",
                "cmr": "/search/",
            }[source]
        )
    ):
        raise ValueError(f"destination outside configured {source} scope")
    return urlunsplit(parts)


def retry_delay(value: str | None, attempt: int) -> float:
    if value:
        try:
            return max(0, float(value))
        except ValueError:
            try:
                return max(0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
            except (ValueError, TypeError):
                pass
    return 0.4 * 2**attempt + random.uniform(0, 0.2)


class Fetcher:
    def __init__(self, root: Path, cfg: Config, client: httpx.Client):
        self.root = root
        self.cfg = cfg
        self.client = client
        self.pages: list[RawPage] = []
        self.retries = 0
        self.deadline = 0.0

    def fetch(
        self,
        source: Source,
        url: str,
        headers: dict | None = None,
        params: dict | None = None,
        *,
        method: str = "GET",
        body: dict | None = None,
    ) -> tuple[Path, httpx.Headers]:
        url = allowed(source, str(httpx.URL(url, params=params)) if params else url)
        seen = {url}
        for _ in range(6):
            for attempt in range(self.cfg.retries + 1):
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"{source} exceeded its request budget")
                retry_after = None
                try:
                    with self.client.stream(
                        method,
                        url,
                        headers=headers,
                        json=body,
                        timeout=min(remaining, self.cfg.timeout_seconds),
                    ) as response:
                        if response.is_redirect:
                            if method != "GET" and response.status_code not in {307, 308}:
                                method, body = "GET", None
                            url = allowed(source, urljoin(url, response.headers["location"]))
                            if url in seen:
                                raise ValueError(f"{source} repeated redirect")
                            seen.add(url)
                            break
                        if response.status_code not in RETRY_STATUS or attempt == self.cfg.retries:
                            response.raise_for_status()
                            return self.save(source, url, response), response.headers
                        retry_after = response.headers.get("Retry-After")
                except httpx.TransportError:
                    if attempt == self.cfg.retries:
                        raise
                delay = retry_delay(retry_after, attempt)
                if time.monotonic() + delay >= self.deadline:
                    raise TimeoutError(f"{source} retry would exceed its request budget")
                time.sleep(delay)
                self.retries += 1
            else:
                raise RuntimeError("retry loop exhausted")
        raise ValueError(f"{source} exceeded redirect limit")

    def save(self, source: Source, url: str, response: httpx.Response) -> Path:
        path = self.root / f"{source}-{len(self.pages):03d}.raw"
        size = 0
        try:
            with path.open("wb") as stream:
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES[source] or time.monotonic() > self.deadline:
                        raise ValueError(f"{source} exceeded response budget")
                    stream.write(chunk)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        headers = response.headers
        self.record(
            source,
            path,
            url,
            "live",
            status=response.status_code,
            media_type=headers.get("Content-Type"),
            revision=headers.get("Last-Modified") or headers.get("ETag"),
            hits=int(headers["CMR-Hits"]) if headers.get("CMR-Hits", "").isdigit() else None,
        )
        return path

    def record(self, source: Source, path: Path, url: str, mode: str, **metadata) -> None:
        self.pages.append(
            RawPage(
                source=source,
                path=path.name,
                url=url,
                mode=mode,
                retrieved_at=datetime.now(UTC),
                sha256=file_hash(path),
                size=path.stat().st_size,
                **metadata,
            )
        )

    def imported(self, source: Source, path: Path, url: str, revision: str | None) -> None:
        if path.stat().st_size > MAX_BYTES[source]:
            raise ValueError(f"{source} import exceeds byte budget")
        target = self.root / f"{source}-{len(self.pages):03d}.raw"
        shutil.copyfile(path, target)
        self.record(source, target, url, "import", revision=revision)

    def cdse(self) -> None:
        import json

        url = CDSE
        seen = set()
        for _ in range(self.cfg.cdse_pages):
            if url in seen:
                raise ValueError("repeated CDSE pagination URL")
            seen.add(url)
            path, _ = self.fetch("cdse", url)
            payload = json.loads(path.read_bytes())
            if not payload["collections"]:
                return
            link = next((link for link in payload.get("links", []) if link["rel"] == "next"), None)
            if not link:
                return
            if link.get("method", "GET") != "GET":
                raise ValueError("unexpected CDSE collection paging method")
            url = allowed("cdse", urljoin(url, link["href"]))

    def cmr(self) -> None:
        import json

        for keyword in self.cfg.cmr_keywords:
            headers = {"Accept": "application/vnd.nasa.cmr.umm_results+json;version=1.18.7"}
            params = {"keyword": keyword, "page_size": self.cfg.cmr_page_size}
            seen = set()
            for _ in range(self.cfg.cmr_pages):
                path, response_headers = self.fetch("cmr", CMR, headers, params)
                if not json.loads(path.read_bytes())["items"]:
                    break
                token = response_headers.get("CMR-Search-After")
                if not token:
                    break
                if token in seen:
                    raise ValueError("repeated CMR continuation token")
                seen.add(token)
                headers["CMR-Search-After"] = token

    def cdse_selected(self) -> None:
        for identifier in self.cfg.cdse_collection_ids:
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", identifier):
                raise ValueError("invalid CDSE collection identifier")
            self.fetch("cdse", f"{CDSE}/{identifier}")


def ingest(
    cfg: Config,
    cordis_file: Path | None = None,
    cellar_file: Path | None = None,
    cordis_revision: str | None = None,
) -> SnapshotManifest:
    root = artifacts() / "snapshots"
    root.mkdir(parents=True, exist_ok=True)
    stage = Path(mkdtemp(dir=root, prefix=".snapshot-"))
    started = time.monotonic()
    error = None
    with httpx.Client(headers={"User-Agent": "EUPolicyEO/0.1 metadata research demo"}) as client:
        fetch = Fetcher(stage, cfg, client)
        try:
            fetch.deadline = time.monotonic() + cfg.source_budget_seconds
            if cellar_file:
                fetch.imported("cellar", cellar_file, CELLAR + cfg.celex, None)
            else:
                fetch.fetch(
                    "cellar",
                    CELLAR + cfg.celex,
                    {
                        "Accept": "application/xhtml+xml",
                        "Accept-Language": cfg.language,
                    },
                )
            fetch.deadline = time.monotonic() + cfg.source_budget_seconds
            if cordis_file:
                fetch.imported("cordis", cordis_file, CORDIS, cordis_revision)
            else:
                fetch.fetch("cordis", CORDIS)
            for source in (fetch.cdse, fetch.cdse_selected, fetch.cmr):
                fetch.deadline = time.monotonic() + cfg.source_budget_seconds
                source()
            from .normalization import legal_sections

            legal_sections(stage / fetch.pages[0].path, cfg, fetch.pages[0], "validation")
        except (ValueError, KeyError, TypeError, OSError, httpx.HTTPError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        pages = fetch.pages
        raw_keys = [(p.source, p.url, p.sha256, p.mode, p.revision) for p in pages]
        snapshot_id = digest(json_bytes([cfg.model_dump(), raw_keys, error]))[:24]
        report = {
            "elapsed_seconds": round(time.monotonic() - started, 4),
            "pages": len(pages),
            "bytes": sum(p.size for p in pages),
            "retries": fetch.retries,
        }
        manifest = SnapshotManifest(
            snapshot_id=snapshot_id,
            created_at=datetime.now(UTC),
            status="partial" if error else "success",
            config=cfg.model_dump(),
            pages=pages,
            source_terms=TERMS,
            summary=report,
            error=error,
        )
        write_json(stage / "manifest.json", manifest.model_dump(mode="json"))
        try:
            stage.rename(root / snapshot_id)
        except OSError:
            from .storage import read_json

            existing = root / snapshot_id / "manifest.json"
            if not existing.exists():
                raise
            shutil.rmtree(stage)
            manifest = SnapshotManifest.model_validate(read_json(existing))
        write_json(
            artifacts() / "last-ingest.json",
            {
                "snapshot_id": snapshot_id,
                "status": manifest.status,
                "error": error,
                "attempted_at": datetime.now(UTC).isoformat(),
                **report,
            },
        )
    return manifest
