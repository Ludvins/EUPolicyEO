"""Evidence-linked screening of EO products for Article 20(1)(b)."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .geometry import boxes_overlap, split_bbox
from .schemas import BBox, Constraints, EOCollection, MonitoringRequirement
from .storage import digest, json_bytes, read_json

Status = Literal["meets", "partial", "fails", "unknown"]

REQUIREMENT_ID = "32024R1991:eng:20:1:b:r0"
LEGAL_BASE = "https://eur-lex.europa.eu/eli/reg/2024/1991/oj/eng"
LEGAL_URL = f"{LEGAL_BASE}#art_20"
TCD_GROUP = "https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover"
TCD_2024_VALIDATION = (
    "https://land.copernicus.eu/en/technical-library/validation-report-tree-cover-density-2024/"
    "%40%40download/file"
)
URBAN_ATLAS = "https://land.copernicus.eu/en/products/urban-atlas/urban-atlas-2021"
CLCPLUS = "https://land.copernicus.eu/en/products/clc-backbone?tab=technical_summary"
PROVIDER_CHECKS = Path(__file__).with_name("suitability_source_checks.json")


class AssessmentScenario(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = "andalusia-urban-screening"
    title: str = "Andalusia urban monitoring"
    bbox: BBox = (-7.5, 36.0, -1.5, 38.8)
    start_year: int = Field(2021, ge=1900, le=2100)
    end_year: int = Field(2024, ge=1900, le=2100)
    max_raster_resolution_m: float = Field(20, gt=0, allow_inf_nan=False)
    max_urban_mapping_unit_ha: float = Field(0.25, gt=0, allow_inf_nan=False)
    max_cadence_years: int = Field(1, ge=1, le=100)

    @model_validator(mode="after")
    def ordered(self):
        Constraints(bbox=self.bbox)
        if self.start_year > self.end_year:
            raise ValueError("start_year follows end_year")
        return self


DEFAULT_SCENARIO = AssessmentScenario()


@dataclass(frozen=True)
class ProductDocumentation:
    code: str
    source_url: str
    cadence_years: int
    canopy: tuple[Status, str]
    green_space: tuple[Status, str]
    scope: tuple[Status, str]
    accuracy_url: str
    accuracy_limit: str
    mapping_unit_ha: float | None = None


PRODUCTS = (
    ProductDocumentation(
        "clms_vlcc_tree-cover-density_europe_10m_yearly_v1",
        f"{TCD_GROUP}/tree-cover-density-2018-present-raster-10-m-europe-yearly",
        1,
        ("meets", "Fractional tree crown cover matches the canopy measurement."),
        ("partial", "Tree crown cover contributes one component of the green-space indicator."),
        (
            "partial",
            "Aggregate the raster inside the urban ecosystem boundaries used for reporting.",
        ),
        TCD_2024_VALIDATION,
        "CLMS reports EU-wide and biogeographical-region validation of the 2024 10 m layer. "
        "This assessment has no comparable validation for the selected urban indicator and area.",
    ),
    ProductDocumentation(
        "clms_vlcc_tree-cover-density_europe_100m_yearly_v1",
        f"{TCD_GROUP}/tree-cover-density-2018-present-raster-100-m-europe-yearly",
        1,
        ("meets", "Aggregated fractional crown cover matches the canopy measurement."),
        ("partial", "Tree crown cover contributes one component of the green-space indicator."),
        ("partial", "Urban boundaries and mixed edge cells require separate treatment."),
        TCD_2024_VALIDATION,
        "The cited validation concerns the native 10 m product. It does not establish the "
        "accuracy of the 100 m aggregation for this urban area.",
    ),
    ProductDocumentation(
        "clms_urban-atlas_land-cover-use_europe_V025ha_vector_static_v01",
        URBAN_ATLAS,
        3,
        ("fails", "Land-use and land-cover classes do not quantify fractional tree crown cover."),
        (
            "partial",
            "Selected mapped green and water classes provide candidate inputs. "
            "The class mapping and completeness for the legal indicator need verification.",
        ),
        (
            "partial",
            "Functional Urban Areas are the product's mapping units. Align them with "
            "the urban ecosystem areas used for reporting.",
        ),
        URBAN_ATLAS,
        "Provider land-use and land-cover validation is separate from validating a derived "
        "green-space estimate in the selected area.",
        mapping_unit_ha=0.25,
    ),
    ProductDocumentation(
        "clms_vlcc_forest-type_europe_10m_3yearly_v1",
        f"{TCD_GROUP}/forest-type-2018-present-raster-10-m-europe-3-yearly",
        3,
        ("fails", "The forest classes exclude urban trees and do not quantify urban crown cover."),
        ("fails", "The forest classes omit urban trees and the other green-space components."),
        ("fails", "The product definition explicitly excludes urban trees."),
        f"{TCD_GROUP}/forest-type-2018-present-raster-10-m-europe-3-yearly",
        "The forest-type accuracy documentation does not validate either urban indicator.",
    ),
)

ASSESSMENT_COLLECTION_IDS = frozenset(f"cdse:{product.code}" for product in PRODUCTS)

INDICATORS = (
    {
        "id": "canopy",
        "label": "Urban tree canopy cover",
        "description": "Area of tree cover from CLMS Tree Cover Density, with appropriate "
        "supplementary data where available.",
        "source_url": f"{LEGAL_BASE}#art_3",
    },
    {
        "id": "green_space",
        "label": "Urban green space",
        "description": "Area of the vegetation and inland-water components specified in Article "
        "3(20), based on CLMS data with appropriate supplementary data where available.",
        "source_url": f"{LEGAL_BASE}#art_3",
    },
)


def _criterion(key: str, label: str, value: tuple[Status, str], source_url: str) -> dict:
    status, detail = value
    return {
        "key": key,
        "label": label,
        "status": status,
        "detail": detail,
        "source_url": source_url,
    }


def _coverage(collection: EOCollection, scenario: AssessmentScenario) -> tuple[Status, str]:
    bounds = collection.bbox_parts
    if not bounds:
        return "unknown", "The catalogue has no usable geographic extent."
    if not any(
        boxes_overlap(bound, target) for bound in bounds for target in split_bbox(scenario.bbox)
    ):
        return "fails", "No catalogue bounding rectangle intersects the screening area."
    if (-180, -90, 180, 90) in bounds:
        return (
            "unknown",
            "The catalogue uses a global placeholder extent. Confirm valid pixels or "
            "features in each reporting area using the item inventory.",
        )
    return (
        "partial",
        "The catalogue extent intersects the screening area. Intersection does not "
        "establish complete observation coverage.",
    )


def _period(collection: EOCollection, scenario: AssessmentScenario) -> tuple[Status, str]:
    start = datetime(scenario.start_year, 1, 1, tzinfo=UTC)
    end = datetime(scenario.end_year, 12, 31, 23, 59, 59, tzinfo=UTC)
    if not collection.intervals:
        return "unknown", "The catalogue has no usable time interval."
    if all(
        (item.start is not None and item.start > end) or (item.end is not None and item.end < start)
        for item in collection.intervals
    ):
        return "fails", "No documented catalogue interval intersects the scenario years."
    if all(item.start is None and item.end is None for item in collection.intervals):
        return "unknown", "The catalogue time interval has no documented endpoints."
    return (
        "partial",
        "The catalogue advertises a time range that may intersect the scenario. A "
        "range alone cannot verify an observation for each requested year and location.",
    )


def _resolution(
    collection: EOCollection, documented: ProductDocumentation, scenario: AssessmentScenario
) -> tuple[Status, str]:
    if documented.mapping_unit_ha is not None:
        area = documented.mapping_unit_ha
        maximum = scenario.max_urban_mapping_unit_ha
        if area > maximum:
            return (
                "fails",
                f"Urban mapping unit {area:g} ha exceeds the scenario maximum {maximum:g} ha.",
            )
        return (
            "partial",
            f"The {area:g} ha urban mapping unit meets the scenario detail threshold, "
            "but the provider uses coarser limits for rural classes.",
        )
    value = collection.spatial_resolution_m
    maximum = scenario.max_raster_resolution_m
    if value is None:
        return "unknown", "The catalogue has no usable raster grid spacing."
    status = "meets" if value <= maximum else "fails"
    return status, f"{value:g} m grid spacing against the scenario maximum of {maximum:g} m."


def _product(
    collection: EOCollection,
    documented: ProductDocumentation,
    scenario: AssessmentScenario,
    provider_checks: dict,
) -> dict:
    source = documented.source_url
    catalogue = collection.provenance.source_url
    cadence = documented.cadence_years
    maximum = scenario.max_cadence_years
    cadence_match: Status = "meets" if cadence <= maximum else "fails"
    observations = []
    if (
        collection.id == provider_checks["collection_id"]
        and list(scenario.bbox) == provider_checks["bbox"]
    ):
        observations = [
            row
            for row in provider_checks["yearly_samples"]
            if scenario.start_year <= row["year"] <= scenario.end_year and row["items"]
        ]
    coverage = _coverage(collection, scenario)
    period = _period(collection, scenario)
    observation_source = catalogue
    if observations:
        observation_source = observations[-1]["url"]
        count = sum(len(row["items"]) for row in observations)
        years = ", ".join(str(row["year"]) for row in observations)
        coverage = (
            "partial",
            f"{count} sampled item envelopes intersect the screening rectangle. "
            "Coverage of every urban ecosystem area and valid pixels remain unverified.",
        )
        period = (
            "partial",
            f"The bounded item sample has reference years {years}. "
            "It does not establish a complete series for every reporting area.",
        )
    shared = [
        _criterion("urban_scope", "Urban reporting area", documented.scope, source),
        _criterion("coverage", "Geographic coverage", coverage, observation_source),
        _criterion("time_coverage", "Observation years", period, observation_source),
        _criterion(
            "resolution", "Spatial detail", _resolution(collection, documented, scenario), source
        ),
        _criterion(
            "cadence",
            "Product cadence",
            (
                cadence_match,
                f"Product cycle of {cadence} yr against the scenario maximum of {maximum} yr.",
            ),
            source,
        ),
        _criterion(
            "accuracy",
            "Indicator accuracy",
            ("unknown", documented.accuracy_limit),
            documented.accuracy_url,
        ),
    ]
    results = []
    for indicator, measurement in (
        ("canopy", documented.canopy),
        ("green_space", documented.green_space),
    ):
        criteria = [_criterion("measurement", "Measured variable", measurement, source)]
        criteria.extend(row.copy() for row in shared)
        statuses = {row["status"] for row in criteria}
        if "fails" in statuses:
            status = "fails"
            summary = "At least one scenario criterion is not met."
        elif "partial" in statuses:
            status = "partial"
            summary = (
                "Supports part of the assessment. Additional evidence or processing is required."
            )
        elif "unknown" in statuses:
            status = "unknown"
            summary = "The supplied evidence is insufficient to decide suitability."
        else:
            status = "meets"
            summary = "All screening criteria are documented as met."
        results.append(
            {"indicator": indicator, "status": status, "summary": summary, "criteria": criteria}
        )
    return {
        "id": collection.id,
        "title": collection.title,
        "source_url": source,
        "catalogue_url": catalogue,
        "catalogue_raw_sha256": collection.provenance.raw_sha256,
        "observation_sample": {
            "captured_at": provider_checks["captured_at"],
            "basis": "One response per year, limited to three intersecting item envelopes. "
            "Raster assets, pixels and completeness were outside the check.",
            "years": observations,
        }
        if observations
        else None,
        "results": results,
    }


def _legal(
    requirement: MonitoringRequirement, requirements: dict[str, MonitoringRequirement]
) -> dict:
    related = []
    for suffix, prefix, label in (
        (":20:3", "the monitoring in accordance with paragraph 1, points (b)", "Article 20(3)"),
        (
            ":20:6",
            "the monitoring in accordance with paragraph 1, points (a) and (b)",
            "Article 20(6)",
        ),
    ):
        for row in requirements.values():
            if row.section_id.endswith(suffix) and row.verbatim_evidence.casefold().startswith(
                prefix
            ):
                related.append(
                    {"provision": label, "text": row.verbatim_evidence, "source_url": LEGAL_URL}
                )
                break
    related.extend(
        [
            {
                "provision": "Article 8(1)",
                "text": "The no-net-loss target uses a 2024 baseline.",
                "source_url": f"{LEGAL_BASE}#art_8",
            },
            {
                "provision": "Article 14(4)",
                "text": "Member States determine and map urban ecosystem areas.",
                "source_url": f"{LEGAL_BASE}#art_14",
            },
        ]
    )
    return {
        "id": requirement.id,
        "provision": "Article 20(1)(b)",
        "source_url": LEGAL_URL,
        "verbatim": requirement.verbatim_evidence,
        "lead_in": requirement.parent_evidence,
        "scope": requirement.area_text,
        "related": related,
    }


def build_assessment(
    snapshot_id: str,
    requirements: Iterable[MonitoringRequirement],
    collections: Iterable[EOCollection],
    *,
    scenario: AssessmentScenario = DEFAULT_SCENARIO,
) -> dict:
    """Build a replayable metadata screen using records present in the supplied snapshot."""
    legal = {row.id: row for row in requirements}
    requirement = legal.get(REQUIREMENT_ID)
    if requirement is None:
        raise LookupError("Article 20(1)(b) is absent from the snapshot")
    candidates = {row.id: row for row in collections if row.id in ASSESSMENT_COLLECTION_IDS}
    if any(row.provenance.snapshot_id != snapshot_id for row in candidates.values()):
        raise ValueError("assessment catalogue records do not match the requested snapshot")
    provider_checks = read_json(PROVIDER_CHECKS)
    products = [
        _product(candidates[record_id], item, scenario, provider_checks)
        for item in PRODUCTS
        if (record_id := f"cdse:{item.code}") in candidates
    ]
    scenarios = scenario.model_dump(
        mode="json",
        exclude={"max_raster_resolution_m", "max_urban_mapping_unit_ha", "max_cadence_years"},
    )
    scenarios["thresholds"] = {
        "max_raster_resolution_m": scenario.max_raster_resolution_m,
        "max_urban_mapping_unit_ha": scenario.max_urban_mapping_unit_ha,
        "max_cadence_years": scenario.max_cadence_years,
        "accuracy": "Validate the derived indicator against independent local reference data.",
    }
    scenarios["basis"] = (
        "The area, analysis window and product requirements are illustrative choices for local "
        "screening. The earlier years are contextual comparison years. The rectangle is a search "
        "area, while reporting uses the mapped Article 14(4) urban ecosystem areas."
    )
    result = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "scenario": scenarios,
        "requirement": _legal(requirement, legal),
        "indicators": [indicator.copy() for indicator in INDICATORS],
        "products": products,
        "missing_product_ids": sorted(ASSESSMENT_COLLECTION_IDS - candidates.keys()),
        "gaps": [
            {
                "indicator": "canopy",
                "summary": "Urban boundaries and local validation are still required.",
                "next_step": "Check yearly tile availability and valid pixels, clip to the mapped urban "
                "ecosystem areas, and validate the area-weighted canopy estimate.",
                "source_url": f"{LEGAL_BASE}#art_14",
            },
            {
                "indicator": "green_space",
                "summary": "The screened products do not supply the full green-space indicator.",
                "next_step": "Check CLCplus Backbone land-cover classes and suitable supplementary data. "
                "Document how mapped classes represent vegetation and inland water within the same boundaries.",
                "source_url": CLCPLUS,
            },
        ],
        "assessment_scope": "Catalogue, provider documentation and bounded item-metadata screening. No raster pixels, "
        "urban boundaries, or derived indicator values were evaluated.",
    }
    return {"assessment_id": digest(json_bytes(result))[:24], **result}
