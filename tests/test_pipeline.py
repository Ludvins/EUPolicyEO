import subprocess
from datetime import UTC, datetime
from time import monotonic

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from eupolicyeo.api import create_app
from eupolicyeo.bundle import Bundle, build, code_revision
from eupolicyeo.evaluation import measures
from eupolicyeo.geometry import compatibility, split_bbox
from eupolicyeo.normalization import normalize
from eupolicyeo.publication import PagesConfig, export, stage_release, unpack, validate
from eupolicyeo.requirements import extract_snapshot
from eupolicyeo.retrieval import bm25, tokenize
from eupolicyeo.schemas import Constraints, SearchQuery
from eupolicyeo.settings import Config
from eupolicyeo.sources import CDSE, TERMS, Fetcher, allowed
from eupolicyeo.storage import file_hash, json_bytes, snapshot_dir, write_json


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("EUPOLICYEO_ARTIFACTS", str(tmp_path))
    snapshot_id = "a" * 24
    root = snapshot_dir(snapshot_id)
    root.mkdir(parents=True)
    # Minimal authored test inputs patterned on upstream structures.
    legal = """<p class="oj-hd-lg">EN</p><p class="oj-doc-ti">REGULATION (EU) 2024/1991</p>
      <p>Recital: Member States shall monitor a recital.</p>
      <div id="art_20" class="eli-subdivision"><p class="oj-ti-art">Article 20</p>
        <div class="eli-title">Monitoring</div><div><p class="oj-normal">
          1. Member States shall monitor the following:</p>
          <table><tr><td>(a)</td><td><p>forest habitat condition and tree cover every two years;</p>
            <table><tr><td>(i)</td><td><p>tree cover within urban ecosystem areas;</p></td></tr></table>
          </td></tr></table>
        </div></div>"""
    csv = '\ufeff"id";"title";"objective"\n"123";"Forest habitat restoration tree study";"tree\ncover trials"\n"124";"Another forest";""\n"x";"broken";""\n'
    stac = {
        "collections": [
            {
                "id": "clms_test",
                "title": "Forest Tree Cover",
                "description": "Forest habitat condition and tree mapping.",
                "extent": {
                    "spatial": {"bbox": [[170, -10, -170, 10], [10, 10, 15, 15]]},
                    "temporal": {
                        "interval": [
                            ["2020-01-01T00:00Z", "2022-01-01T00:00Z"],
                            ["2024-01-01T00:00Z", None],
                        ]
                    },
                },
            }
        ]
    }
    cmr_item = {
        "meta": {"concept-id": "C1-NASA", "revision-id": 2, "provider-id": "NASA"},
        "umm": {
            "EntryTitle": "Forest tree density",
            "Abstract": "Forest tree density.",
            "TemporalExtents": [{"SingleDateTimes": ["2020-01-01T00:00:00Z"]}],
            "ScienceKeywords": [{"Category": "Forest"}],
            "RelatedUrls": [{"Type": "DATA SET LANDING PAGE", "URL": "https://doi.org/10.1/test"}],
        },
    }
    cmr = {"items": [cmr_item, {**cmr_item, "meta": {**cmr_item["meta"], "revision-id": 1}}]}
    pages = []
    for source, payload in [
        ("cellar", legal.encode()),
        ("cordis", csv.encode()),
        ("cdse", json_bytes(stac)),
        ("cmr", json_bytes(cmr)),
    ]:
        path = root / f"{source}.raw"
        path.write_bytes(payload)
        pages.append(
            {
                "source": source,
                "path": path.name,
                "url": TERMS[source],
                "sha256": file_hash(path),
                "size": len(payload),
                "mode": "import",
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
        )
    write_json(
        root / "manifest.json",
        {
            "snapshot_id": snapshot_id,
            "status": "success",
            "config": {},
            "created_at": datetime.now(UTC).isoformat(),
            "pages": pages,
            "source_terms": TERMS,
            "summary": {"elapsed_seconds": 1.0},
        },
    )
    return snapshot_id


def test_ingest_cache_to_api_and_publication(snapshot, tmp_path, monkeypatch):
    report = normalize(snapshot)
    assert report["sources"]["cordis"] == {"parsed": 3, "rejected": 1, "accepted": 2}
    assert report["sources"]["cmr"]["duplicate"] == 1
    requirements = extract_snapshot(snapshot)
    assert len(requirements) == 2
    assert all(req.actor == "Member States" and req.parent_evidence for req in requirements)
    assert requirements[0].frequency_text == "every two years"
    bundle = build(snapshot, "bm25")
    assert bundle.collections["cmr:C1-NASA"].provenance.revision == "2"
    assert bundle.docs["projects"][0].description == "tree cover trials"
    assert bundle.docs["projects"][1].description is None
    assert Bundle(bundle.root).search(SearchQuery(corpus="eo", query="forest"))
    assert not bundle.search(SearchQuery(corpus="eo", query="qsjagz"))
    client = TestClient(create_app(lambda: ("7", bundle, None)))
    with client:
        assert client.get("/readyz").json() == {"ready": True}
        reco = client.post("/recommend", json={"requirement_id": requirements[0].id}).json()
        assert reco["model_version"] == "7"
        assert [result["id"] for result in reco["eo"]] == ["cdse:clms_test"]
        assert [result["id"] for result in reco["projects"]] == ["cordis:123"]
        assert reco["evidence"]["requirement"]["verbatim_evidence"].endswith(";")
        assert (
            client.post("/search", json={"query": "a", "corpus": "eo", "top_k": 999}).status_code
            == 422
        )
        assert client.get("/collections/none").status_code == 404
        assert 'status_class="4xx"' in client.get("/metrics").text
    public = tmp_path / "release"
    monkeypatch.setattr("eupolicyeo.publication.code_revision", lambda: "a" * 40)
    m = export(bundle, "7", PagesConfig(include_dense=False), public)
    assert m["source_counts"] == {"cellar": 2, "cordis": 2, "cdse": 1, "cmr": 1}
    assert validate(public)["release_id"] == m["release_id"]
    staged = stage_release(public, tmp_path / "public")
    assert staged == m
    active = tmp_path / "public" / "active.json"
    pointer = active.read_bytes()
    with pytest.raises(ValueError, match="Git revision"):
        stage_release(public, tmp_path / "public", git_revision="b" * 40)
    assert active.read_bytes() == pointer
    assert stage_release(public, tmp_path / "public", git_revision=m["git_revision"]) == m
    (public / "projects.json").write_text("[]")
    with pytest.raises(ValueError, match="hash"):
        validate(public)
    (snapshot_dir(snapshot) / "cordis.raw").write_text("altered")
    with pytest.raises(ValueError, match="hash"):
        normalize(snapshot)


def test_no_model_readiness():
    def missing():
        raise ValueError("no validated model")

    with TestClient(create_app(missing)) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 503


def test_revision_requires_a_clean_source_checkout(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    source = root / "src" / "eupolicyeo" / "bundle.py"
    source.parent.mkdir(parents=True)
    source.write_text("# pristine\n", encoding="utf-8")
    (root / ".gitignore").write_text("artifacts/\n", encoding="utf-8")
    monkeypatch.setattr("eupolicyeo.bundle.__file__", str(source))
    monkeypatch.chdir(tmp_path)

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    assert code_revision() is None
    git("init")
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "Test source")
    revision = git("rev-parse", "HEAD")
    (root / "artifacts").mkdir()
    (root / "artifacts" / "export.json").write_text("{}", encoding="utf-8")
    assert code_revision() == revision
    source.write_text("# modified\n", encoding="utf-8")
    assert code_revision() is None
    git("restore", "src/eupolicyeo/bundle.py")
    (root / "untracked.py").touch()
    assert code_revision() is None


def test_geometry_and_temporal_gap(snapshot):
    normalize(snapshot)
    extract_snapshot(snapshot)
    doc = build(snapshot, "bm25").collections["cdse:clms_test"]
    assert split_bbox((170, -1, -170, 1)) == [(170, -1, 180, 1), (-180, -1, -170, 1)]
    assert compatibility(doc, Constraints(bbox=(179, 0, -179, 9))) == "compatible"
    assert (
        compatibility(doc, Constraints(start="2023-01-01T00:00:00Z", end="2023-07-01T00:00:00Z"))
        == "incompatible"
    )
    assert compatibility(doc, Constraints(start="2026-01-01T00:00:00Z")) == "compatible"
    with pytest.raises(ValidationError):
        Constraints(bbox=(12, 30, 20, 10))


def test_metrics_and_tokenization():
    values = measures(["unjudged", "relevant", "no"], {"relevant": 2, "no": 0, "partial": 1})
    assert values["mrr10"] == 0.5
    assert values["judged_precision10"] == 0.5
    assert values["judged_coverage10"] == pytest.approx(2 / 3)
    assert values["pooled_recall5"] == 0.5
    assert tokenize("CAFÉ ſentinel_2 2024/1991") == ["café", "sentinel", "2", "2024", "1991"]
    assert bm25({"k1": 1.2, "b": 0.75, "lengths": [1], "average": 1, "postings": {}}, "none") == {}


def test_retry_redirect_and_page_cycle(tmp_path):
    requests = []

    def handler(req: httpx.Request):
        requests.append(req)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200, json={"collections": [{"id": "seen"}], "links": [{"rel": "next", "href": CDSE}]}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetch = Fetcher(tmp_path, Config(), client)
        fetch.deadline = monotonic() + 4
        with pytest.raises(ValueError, match="pagination"):
            fetch.cdse()
    assert fetch.retries == 1 and len(requests) == 2 and len(fetch.pages) == 1
    assert allowed("cellar", "http://publications.europa.eu/resource/cellar/id").startswith(
        "https:"
    )
    with pytest.raises(ValueError):
        allowed("cmr", "https://evil.invalid/search/")


def test_archive_traversal(tmp_path):
    from zipfile import ZipFile

    archive = tmp_path / "bad.zip"
    with ZipFile(archive, "w") as stream:
        stream.writestr("../bad.json", "{}")
    with pytest.raises(ValueError, match="unsafe"):
        unpack(archive, file_hash(archive), tmp_path / "extract")
