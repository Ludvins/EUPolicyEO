from datetime import UTC, datetime

import pytest

from eupolicyeo.entity_resolution import (
    Identity,
    IdentityAdvice,
    _candidate_pairs,
    _pair,
    compare_snapshots,
    llm_adjudicator,
    refresh_snapshot,
    resolve_snapshot,
)
from eupolicyeo.schemas import EOCollection, Provenance, RawPage, SnapshotManifest
from eupolicyeo.settings import Config
from eupolicyeo.storage import file_hash


def sample(identifier, **overrides):
    fields = {
        "id": identifier,
        "source": "cdse",
        "provider": "CDSE",
        "title": "Illustrative vegetation cover",
        "source_url": "https://example.com/collection",
        "source_revision": None,
        "raw_sha256": "a" * 64,
        "doi": "10.1000/example",
        "edition": "v1",
        "delivery_stem": "clms_sample_v1",
        "format": "COG",
        "spatial_resolution_m": 300,
        "bbox_parts": ((0, 0, 2, 2),),
        "intervals": (("2001-01-01", "2002-01-01", False),),
        "platforms": (),
        "instruments": (),
    }
    return Identity.model_validate(fields | overrides)


def test_groups_formats_only_and_preserves_both_records(monkeypatch):
    a = sample("cdse:clms_sample_v1_cog")
    b = sample("cdse:clms_sample_v1_nc", format="NetCDF")
    separate = sample("cmr:sample", source="cmr", provider="TEST", format=None, delivery_stem=None)
    records = {item.id: item for item in (a, b, separate)}
    monkeypatch.setattr(
        "eupolicyeo.entity_resolution._read_inventory", lambda _: (None, None, records)
    )
    model_review = []

    def advise(pair):
        model_review.append(pair["id"])
        return {"advice": {"decision": "same_delivery_family"}}

    resolved = resolve_snapshot("illustrative", adjudicator=advise, review_limit=1)
    assert resolved["family_count"] == 1
    assert set(resolved["membership"]) == {a.id, b.id}
    assert resolved["ungrouped_records"] == 1
    assert resolved["shared_cross_catalogue_dois"] == [a.doi]
    assert resolved["llm_reviews"][0]["pair_id"] == model_review[0]
    assert resolved["pair_counts"] == {"group_formats": 1, "keep_distinct": 0, "review": 2}


@pytest.mark.parametrize(
    ("changes", "decision"),
    [
        ({"format": None}, "review"),
        ({"doi": None}, "review"),
        ({"edition": "v2"}, "keep_distinct"),
        ({"spatial_resolution_m": 1000}, "keep_distinct"),
        ({"bbox_parts": ((0, 0, 1, 1),)}, "keep_distinct"),
        ({"intervals": (("2001-01-01", "2003-01-01", False),)}, "keep_distinct"),
    ],
)
def test_missing_and_conflicting_evidence_blocks_grouping(changes, decision):
    a = sample("cdse:clms_sample_v1_cog")
    b = sample("cdse:clms_sample_v1_nc", **({"format": "NetCDF"} | changes))
    candidates = _candidate_pairs({a.id: a, b.id: b})
    assert _pair(a, b, candidates[a.id, b.id])["decision"] == decision


def test_model_citations_must_exist_in_supplied_evidence():
    a = sample("cdse:clms_sample_v1_cog", doi=None)
    b = sample("cdse:clms_sample_v1_nc", format="NetCDF")

    class BadCitation:
        identity = {"name": "synthetic-test-engine"}

        def generate(self, system, prompt, schema):
            assert (
                "left.doi"
                not in schema.model_json_schema()["properties"]["evidence_fields"]["items"]["enum"]
            )
            return IdentityAdvice(
                decision="same_delivery_family",
                reason="A claimed common DOI",
                evidence_fields=["left.doi"],
            ), {}

    with pytest.raises(ValueError, match="unavailable evidence field"):
        llm_adjudicator(BadCitation())(_pair(a, b, ["same_delivery_stem"]))


def test_revision_diff_records_changes_without_asserting_deletion(monkeypatch):
    old_snapshot, new_snapshot = "1" * 24, "2" * 24
    stamp = datetime(2025, 1, 1, tzinfo=UTC)

    def data(snapshot, record_names, revision, title):
        manifest = SnapshotManifest(
            snapshot_id=snapshot,
            created_at=stamp,
            status="success",
            config={},
            pages=[],
            source_terms={},
            summary={},
        )
        documents = {}
        evidence = {}
        for record in record_names:
            row = sample("cmr:" + record, source="cmr", source_revision=revision)
            evidence[row.id] = row
            documents[row.id] = EOCollection(
                id=row.id,
                title=title,
                provenance=Provenance(
                    source="cmr",
                    source_id=record,
                    source_url=row.source_url,
                    retrieved_at=stamp,
                    raw_sha256=row.raw_sha256,
                    snapshot_id=snapshot,
                    revision=revision,
                ),
            )
        return manifest, documents, evidence

    sources = {
        old_snapshot: data(old_snapshot, ("shared", "old"), "1", "Earlier title"),
        new_snapshot: data(new_snapshot, ("shared", "new"), "2", "Current title"),
    }
    monkeypatch.setattr("eupolicyeo.entity_resolution._read_inventory", sources.__getitem__)
    result = compare_snapshots(old_snapshot, new_snapshot)
    assert result["newly_observed"] == ["cmr:new"]
    assert result["no_longer_observed"] == ["cmr:old"]
    assert result["changed"] == [
        {
            "id": "cmr:shared",
            "source_url": "https://example.com/collection",
            "previous_revision": "1",
            "current_revision": "2",
            "changed_fields": ["title"],
        }
    ]


@pytest.mark.parametrize("complete", [True, False])
def test_bounded_refresh_reuses_archived_cordis_and_cellar(tmp_path, monkeypatch, complete):
    stamp = datetime(2025, 1, 1, tzinfo=UTC)
    old_id, new_id = "1" * 24, "2" * 24
    pages = []
    for source in ("cordis", "cellar"):
        path = tmp_path / f"{source}.raw"
        path.write_text("synthetic unit-test fixture", encoding="utf-8")
        pages.append(
            RawPage(
                source=source,
                path=path.name,
                url="https://example.com",
                retrieved_at=stamp,
                sha256=file_hash(path),
                size=path.stat().st_size,
                mode="import",
            )
        )
    before = SnapshotManifest(
        snapshot_id=old_id,
        created_at=stamp,
        config=Config().model_dump(),
        status="success",
        pages=pages,
        source_terms={},
        summary={},
    )
    after = before.model_copy(
        update={
            "snapshot_id": new_id,
            "status": "success" if complete else "partial",
            "error": None if complete else "sample timeout",
        }
    )

    def ingest(cfg, cordis_file, cellar_file, cordis_revision):
        assert cfg.cdse_pages == 1
        assert cordis_file == tmp_path / "cordis.raw"
        assert cellar_file == tmp_path / "cellar.raw"
        return after

    def normalize(snapshot):
        assert complete and snapshot == new_id
        return {"sources": {}}

    monkeypatch.setattr("eupolicyeo.entity_resolution._read_inventory", lambda _: (before, {}, {}))
    monkeypatch.setattr("eupolicyeo.entity_resolution.snapshot_dir", lambda _: tmp_path)
    monkeypatch.setattr("eupolicyeo.entity_resolution.ingest", ingest)
    monkeypatch.setattr("eupolicyeo.entity_resolution.normalize", normalize)
    monkeypatch.setattr(
        "eupolicyeo.entity_resolution.compare_snapshots", lambda old, new: {"pair": [old, new]}
    )

    candidate = refresh_snapshot(old_id, Config(cdse_pages=1))
    assert candidate["reused_input_sha256"] == {row.source: row.sha256 for row in pages}
    if complete:
        assert candidate["comparison"] == {"pair": [old_id, new_id]}
    else:
        assert candidate["error"] == "sample timeout"
        assert "comparison" not in candidate
