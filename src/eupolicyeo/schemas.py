from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

Source = Literal["cellar", "cordis", "cdse", "cmr"]
Corpus = Literal["eo", "projects"]
BBox = tuple[float, float, float, float]
Compatibility = Literal["compatible", "incompatible", "unknown", "not_requested"]


class Provenance(BaseModel):
    source: Source
    source_id: str
    source_url: str
    retrieved_at: AwareDatetime
    raw_sha256: str
    snapshot_id: str
    revision: str | None = None


class LegalSection(BaseModel):
    id: str
    celex: str
    language: str
    version_type: Literal["original"] = "original"
    article: str
    paragraph: str | None = None
    point: str | None = None
    kind: Literal["article"] = "article"
    title: str | None = None
    text: str
    parent_id: str | None = None
    raw_xpath: str
    provenance: Provenance


class EvidenceUse(BaseModel):
    role: Literal["direct_measurement", "research_method", "supporting_context"]
    note: str
    source_url: str


class RetrievalProfile(BaseModel):
    query: str | None
    evidence_groups: list[list[str]] = Field(default_factory=list)
    record_evidence: dict[str, EvidenceUse] = Field(default_factory=dict)


class MonitoringRequirement(BaseModel):
    id: str
    section_id: str
    verbatim_evidence: str
    evidence_start: int
    evidence_end: int
    actor: str | None = None
    modality: Literal["obligation", "permission", "recommendation", "context", "unknown"]
    action: str | None = None
    observable: str | None = None
    area_text: str | None = None
    frequency_text: str | None = None
    deadline_text: str | None = None
    conditions: list[str] = Field(default_factory=list)
    referenced_sections: list[str] = Field(default_factory=list)
    parent_section_id: str | None = None
    parent_evidence: str | None = None
    parent_evidence_start: int | None = None
    parent_evidence_end: int | None = None
    extraction_method: str = "modal-section-v1"
    review_status: Literal["unreviewed", "accepted", "rejected", "edited"] = "unreviewed"
    query: str
    expansions: list[str] = Field(default_factory=list)
    search_profile: RetrievalProfile | None = None


class Interval(BaseModel):
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    ongoing: bool | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("start follows end")
        return self


class SearchDocument(BaseModel):
    id: str
    title: str
    description: str | None = None
    keywords: list[str] = Field(default_factory=list)
    discovery_terms: list[str] = Field(default_factory=list)
    provider: str | None = None
    metadata_quality_flags: list[str] = Field(default_factory=list)
    provenance: Provenance


class ResearchProject(SearchDocument):
    acronym: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    programme: str | None = None
    topics: list[str] = Field(default_factory=list)


class EOCollection(SearchDocument):
    measurement_terms: list[str] = Field(default_factory=list)
    platform: list[str] = Field(default_factory=list)
    instrument: list[str] = Field(default_factory=list)
    bbox_parts: list[BBox] | None = None
    intervals: list[Interval] = Field(default_factory=list)
    temporal_start: AwareDatetime | None = None
    temporal_end: AwareDatetime | None = None
    ongoing: bool | None = None
    spatial_resolution_m: float | None = Field(None, gt=0)
    processing_level: str | None = None
    access_urls: list[str] = Field(default_factory=list)
    license: str | None = None
    use_constraints: bool = False


class EOGranule(BaseModel):
    id: str
    collection_id: str
    bbox_parts: list[BBox] | None = None
    geometry_wkb_hex: str | None = None
    temporal_start: AwareDatetime | None = None
    temporal_end: AwareDatetime | None = None
    cloud_cover_percent: float | None = Field(None, ge=0, le=100)
    metadata_quality_flags: list[str] = Field(default_factory=list)
    provenance: Provenance

    @model_validator(mode="after")
    def ordered(self):
        if self.temporal_start and self.temporal_end and self.temporal_start > self.temporal_end:
            raise ValueError("granule start follows end")
        return self


class Constraints(BaseModel):
    bbox: BBox | None = None
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    strict_metadata: bool = False

    @model_validator(mode="after")
    def valid_constraints(self):
        if self.bbox:
            w, s, e, n = self.bbox
            if not (-180 <= w <= 180 and -180 <= e <= 180 and -90 <= s <= n <= 90):
                raise ValueError("invalid west/south/east/north bbox")
        if self.start and self.end and self.start > self.end:
            raise ValueError("start follows end")
        return self


class SearchQuery(Constraints):
    query: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    corpus: Corpus
    top_k: int = Field(10, ge=1, le=50)


class RecommendationQuery(Constraints):
    requirement_id: str = Field(min_length=1, max_length=160)
    top_k: int = Field(5, ge=1, le=50)


class RankedCandidate(BaseModel):
    id: str
    source: Source
    title: str
    score: float
    score_type: Literal["bm25", "cosine"]
    rank: int
    evidence: str
    source_url: str
    compatibility: Compatibility
    flags: list[str]
    needs_review: bool = True
    provenance: Provenance
    evidence_use: EvidenceUse | None = None


class RawPage(BaseModel):
    source: Source
    path: str
    url: str
    retrieved_at: datetime
    media_type: str | None = None
    status: int | None = None
    revision: str | None = None
    hits: int | None = None
    sha256: str
    size: int
    mode: Literal["live", "import"]


class SnapshotManifest(BaseModel):
    snapshot_id: str
    created_at: datetime
    schema_version: Literal[1] = 1
    status: Literal["success", "partial"]
    config: dict
    pages: list[RawPage]
    source_terms: dict[str, str]
    summary: dict
    error: str | None = None
