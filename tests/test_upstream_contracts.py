from datetime import UTC, datetime
from pathlib import Path

from eupolicyeo.normalization import stac, umm
from eupolicyeo.schemas import RawPage
from eupolicyeo.storage import file_hash, read_json

ROOT = Path(__file__).parent / "fixtures"


def page(source, name, url):
    path = ROOT / name
    return RawPage(
        source=source,
        path=name,
        url=url,
        retrieved_at=datetime.now(UTC),
        sha256=file_hash(path),
        size=path.stat().st_size,
        mode="import",
    )


def test_observed_stac_collection_contract():
    name = "cdse-tree-cover.json"
    raw = read_json(ROOT / name)
    source = page("cdse", name, "https://stac.dataspace.copernicus.eu/v1/collections/" + raw["id"])
    doc = stac(raw, source, "fixture")
    assert doc.id == "cdse:clms_vlcc_tree-cover-density_europe_10m_yearly_v1"
    assert doc.bbox_parts and doc.intervals
    assert doc.provenance.source_url == source.url


def test_observed_cmr_collection_contract():
    name = "cmr-vegetation.json"
    source = page(
        "cmr", name, "https://cmr.earthdata.nasa.gov/search/collections.umm_json?keyword=vegetation"
    )
    doc = umm(read_json(ROOT / name), source, "fixture")
    assert doc.id == "cmr:C2264350397-ORNL_CLOUD"
    assert doc.provenance.revision == "27"
    assert doc.provenance.source_url == "https://doi.org/10.3334/ORNLDAAC/1923"
    assert doc.bbox_parts and doc.temporal_start and doc.platform == ["G-V"]
