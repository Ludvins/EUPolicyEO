from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from eupolicyeo.publication import PagesConfig, export, public_docs
from eupolicyeo.schemas import (
    EOCollection,
    EvidenceUse,
    LegalSection,
    MonitoringRequirement,
    Provenance,
    ResearchProject,
    RetrievalProfile,
)
from eupolicyeo.storage import read_json, write_json


def provenance(source, source_id):
    hosts = {
        "cellar": "eur-lex.europa.eu",
        "cdse": "stac.dataspace.copernicus.eu",
        "cmr": "cmr.earthdata.nasa.gov",
        "cordis": "cordis.europa.eu",
    }
    return Provenance(
        source=source,
        source_id=source_id,
        source_url=f"https://{hosts[source]}/example/{source_id}",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        raw_sha256="0" * 64,
        snapshot_id="0" * 24,
    )


def project(id_, title, objective=None):
    return ResearchProject(
        id=f"cordis:{id_}",
        title=title,
        description=objective,
        keywords=["Private objective keyword"],
        topics=["HORIZON-BIODIV"],
        provenance=provenance("cordis", id_),
    )


def collection(id_, title, restricted=False):
    source, source_id = id_.split(":")
    return EOCollection(
        id=id_,
        title=title,
        description="Private catalogue description",
        access_urls=["https://storage.example"],
        use_constraints=restricted,
        provenance=provenance(source, source_id),
    )


def test_article_topic_reservations_are_bounded_stable_and_discoverable():
    bundle = SimpleNamespace(
        docs={
            "projects": [
                project("1", "University partnership"),
                project("2", "Habitat condition and restoration"),
                project("3", "Cross-population survey", "Monitoring pollinator abundance."),
                project("8", "Pollinator field methods", "Monitoring pollinator abundance."),
                project("9", "Tools for restoration"),
            ],
            "eo": [
                collection("cdse:clms_first", "Solar radiation"),
                collection("cdse:clms_tcd", "Tree Cover Density Europe"),
                collection(
                    "cdse:clms_tcd_restricted", "Tree Cover Density Europe", restricted=True
                ),
                collection("cdse:raw", "Urban Tree Canopy Cover"),
                collection("cmr:C1-EXAMPLE", "Catalog of observations"),
            ],
        }
    )
    legacy = public_docs(bundle, PagesConfig(max_projects=2, max_collections_per_source=1))
    assert [doc.id for doc in legacy["projects"]] == ["cordis:1", "cordis:2"]
    assert [doc.id for doc in legacy["eo"]] == ["cdse:clms_first", "cmr:C1-EXAMPLE"]

    cfg = PagesConfig(max_projects=2, max_collections_per_source=1, coverage_per_topic=1)
    selected = public_docs(bundle, cfg)
    assert selected == public_docs(bundle, cfg)
    assert [doc.id for doc in selected["projects"]] == ["cordis:2", "cordis:8"]
    assert [doc.id for doc in selected["eo"]] == ["cdse:clms_tcd", "cmr:C1-EXAMPLE"]
    assert all(doc.description is None for docs in selected.values() for doc in docs)
    assert all(doc.keywords == ["HORIZON-BIODIV"] for doc in selected["projects"])
    assert all(not doc.access_urls and not doc.use_constraints for doc in selected["eo"])

    more_places = cfg.model_copy(update={"max_projects": 3})
    assert [doc.id for doc in public_docs(bundle, more_places)["projects"]] == [
        "cordis:1",
        "cordis:2",
        "cordis:8",
    ]


def test_export_limits_evidence_use_to_included_records_and_source_hosts(tmp_path):
    stored = {
        key: {
            "source": key,
            "retrieved_at": "2026-01-01T00:00:00Z",
            "mode": "frozen",
            "url": f"https://catalogue.example/{key}",
        }
        for key in ("cellar", "cdse", "cmr", "cordis")
    }
    write_json(
        tmp_path / "snapshot.json",
        {"pages": list(stored.values()), "summary": {}, "created_at": "2026-01-01T00:00:00Z"},
    )
    write_json(tmp_path / "normalization.json", {})
    text = "Member States shall monitor urban tree canopy cover."
    section = LegalSection(
        id="article20.1.b",
        celex="32024R1991",
        language="en",
        article="20",
        paragraph="1",
        point="b",
        text=text,
        raw_xpath="//p",
        provenance=provenance("cellar", "32024R1991"),
    )
    use = EvidenceUse(
        role="direct_measurement",
        note="Measures tree crown cover in each cell.",
        source_url="https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover",
    )
    allowed_id = "cdse:clms_tcd"
    req = MonitoringRequirement(
        id="tree-canopy",
        section_id=section.id,
        verbatim_evidence=text,
        evidence_start=0,
        evidence_end=len(text),
        modality="obligation",
        query="tree cover",
        search_profile=RetrievalProfile(
            query="tree cover",
            evidence_groups=[["tree cover"]],
            record_evidence={allowed_id: use, "cdse:omitted": use},
        ),
    )
    bundle = SimpleNamespace(
        root=tmp_path,
        snapshot="0" * 24,
        ranker="bm25",
        manifest={"build_id": "test"},
        docs={
            "eo": [
                collection(allowed_id, "Tree Cover Density"),
                collection("cmr:C1-EXAMPLE", "Observations"),
            ],
            "projects": [project("1", "University partnership")],
        },
        requirements={req.id: req},
        evidence=lambda copy: {"section": section, "requirement": copy},
    )
    cfg = PagesConfig(include_dense=False)
    public = tmp_path / "public"
    export(bundle, "1", cfg, public)
    profile = read_json(public / "requirements.json")[0]["requirement"]["search_profile"]
    assert profile["record_evidence"] == {allowed_id: use.model_dump()}

    use.source_url = "http://land.copernicus.eu/example"
    with pytest.raises(ValueError, match="invalid public evidence-use source or record"):
        export(bundle, "1", cfg, tmp_path / "invalid")
