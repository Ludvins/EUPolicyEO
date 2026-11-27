from datetime import UTC, datetime

import pytest

from eupolicyeo.schemas import EOCollection, Interval, MonitoringRequirement, Provenance
from eupolicyeo.suitability import PRODUCTS, REQUIREMENT_ID, AssessmentScenario, build_assessment

SNAPSHOT = "1" * 24


def requirement():
    return MonitoringRequirement(
        id=REQUIREMENT_ID,
        section_id="32024R1991:eng:20:1:b",
        verbatim_evidence="Urban canopy and green space.",
        evidence_start=0,
        evidence_end=29,
        modality="obligation",
        area_text="urban ecosystem areas",
        query="urban canopy and green space",
    )


def collection(product, resolution, snapshot=SNAPSHOT):
    source = f"https://stac.dataspace.copernicus.eu/v1/collections/{product.code}"
    return EOCollection(
        id=f"cdse:{product.code}",
        title=product.code,
        bbox_parts=[(-180, -90, 180, 90)],
        spatial_resolution_m=resolution,
        intervals=[Interval(start=datetime(2018, 1, 1, tzinfo=UTC), ongoing=True)],
        provenance=Provenance(
            source="cdse",
            source_id=product.code,
            source_url=source,
            retrieved_at=datetime(2026, 11, 27, tzinfo=UTC),
            raw_sha256="0" * 64,
            snapshot_id=snapshot,
        ),
    )


def criteria(product, indicator):
    result = next(row for row in product["results"] if row["indicator"] == indicator)
    return {row["key"]: row["status"] for row in result["criteria"]}


def test_canopy_measurement_differs_from_overall_suitability_and_green_space():
    rows = [collection(p, fixed) for p, fixed in zip(PRODUCTS, [10, 100, None, 10], strict=True)]
    result = build_assessment(SNAPSHOT, [requirement()], rows)
    assert result == build_assessment(SNAPSHOT, [requirement()], reversed(rows))
    canopy, coarse, atlas, forest = result["products"]
    assert canopy["results"][0]["status"] == "partial"
    assert criteria(canopy, "canopy") == {
        "measurement": "meets",
        "urban_scope": "partial",
        "coverage": "partial",
        "time_coverage": "partial",
        "resolution": "meets",
        "cadence": "meets",
        "accuracy": "unknown",
    }
    assert criteria(canopy, "green_space")["measurement"] == "partial"
    assert criteria(coarse, "canopy")["resolution"] == "fails"
    assert criteria(atlas, "canopy")["measurement"] == "fails"
    assert criteria(atlas, "green_space")["measurement"] == "partial"
    assert criteria(atlas, "green_space")["cadence"] == "fails"
    assert criteria(forest, "canopy")["urban_scope"] == "fails"
    assert result["scenario"]["thresholds"]["max_cadence_years"] == 1
    assert result["requirement"]["scope"] == "urban ecosystem areas"


def test_bounded_observation_evidence_does_not_apply_to_another_area_or_year():
    row = collection(PRODUCTS[0], 10)
    result = build_assessment(SNAPSHOT, [requirement()], [row])
    samples = result["products"][0]["observation_sample"]["years"]
    assert [sample["year"] for sample in samples] == [2021, 2022, 2023, 2024]
    assert all(sample["http_status"] == 200 and len(sample["items"]) == 3 for sample in samples)
    assert sum(len(sample["items"]) for sample in samples) == 12

    other = build_assessment(
        SNAPSHOT,
        [requirement()],
        [row],
        scenario=AssessmentScenario(bbox=(2, 42, 3, 44), start_year=2027, end_year=2027),
    )
    assert other["assessment_id"] != result["assessment_id"]
    product = other["products"][0]
    assert product["observation_sample"] is None
    assert criteria(product, "canopy")["coverage"] == "unknown"
    assert len(other["missing_product_ids"]) == 3


def test_snapshot_binding_and_missing_legal_source():
    with pytest.raises(ValueError, match="requested snapshot"):
        build_assessment(SNAPSHOT, [requirement()], [collection(PRODUCTS[0], 10, "2" * 24)])
    with pytest.raises(LookupError, match="Article 20"):
        build_assessment(SNAPSHOT, [], [])
