import logging
from contextlib import asynccontextmanager
from datetime import datetime
from time import perf_counter

from fastapi import FastAPI, HTTPException, Query, Request, Response
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from pydantic import AwareDatetime, BaseModel, ValidationError

from .bundle import Bundle
from .registry import load
from .schemas import (
    Constraints,
    EOCollection,
    LegalSection,
    MonitoringRequirement,
    RankedCandidate,
    RecommendationQuery,
    RetrievalProfile,
    SearchQuery,
)
from .settings import artifacts
from .storage import read_json
from .suitability import DEFAULT_SCENARIO, AssessmentScenario, build_assessment

LOG = logging.getLogger(__name__)
SOURCES = {"cellar", "cordis", "cdse", "cmr"}
METHODS = {"GET", "POST", "OPTIONS", "HEAD"}


class Version(BaseModel):
    model_version: str
    ranker: str
    snapshot_id: str
    build_id: str
    model_revision: str | None
    git_revision: str | None


class Evidence(BaseModel):
    requirement: MonitoringRequirement
    section: LegalSection
    parent_section: LegalSection | None = None


class SearchResponse(Version):
    results: list[RankedCandidate]


class Recommendation(Version):
    evidence: Evidence
    eo: list[RankedCandidate]
    projects: list[RankedCandidate]
    limitation: str = "Candidate matches require interpretation. Collection extent is a preliminary metadata check."


def create_app(loader=load) -> FastAPI:
    metrics = CollectorRegistry()
    request_count = Counter(
        "eupolicyeo_http_requests",
        "HTTP requests",
        ["route", "method", "status_class"],
        registry=metrics,
    )
    request_time = Histogram(
        "eupolicyeo_http_request_duration_seconds", "HTTP latency", ["route"], registry=metrics
    )
    retrieval_time = Histogram(
        "eupolicyeo_retrieval_duration_seconds",
        "Search latency",
        ["corpus", "ranker"],
        registry=metrics,
    )
    result_count = Counter(
        "eupolicyeo_retrieval_results", "Candidates returned", ["corpus"], registry=metrics
    )
    info = Gauge(
        "eupolicyeo_model_info", "Loaded registry version", ["version", "ranker"], registry=metrics
    )
    records = Gauge(
        "eupolicyeo_snapshot_records", "Accepted canonical records", ["source"], registry=metrics
    )
    rejected = Gauge(
        "eupolicyeo_snapshot_invalid_records", "Rejected records", ["source"], registry=metrics
    )
    freshness = Gauge(
        "eupolicyeo_source_last_success_timestamp_seconds",
        "Last successful source fetch",
        ["source"],
        registry=metrics,
    )
    last = Gauge(
        "eupolicyeo_ingest_last_run", "Last ingest values", ["measurement"], registry=metrics
    )
    missing = Gauge(
        "eupolicyeo_snapshot_missing_fields",
        "Canonical records with missing metadata",
        ["source", "field"],
        registry=metrics,
    )
    top_score = Histogram(
        "eupolicyeo_top_score",
        "Top retrieval score by ranker",
        ["corpus", "ranker"],
        buckets=(-1, 0, 0.25, 0.5, 0.75, 1, 5, 20, 100),
        registry=metrics,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.model = None
        try:
            numeric, bundle, _ = loader()
            bundle.smoke()
            manifest = bundle.manifest
            app.state.model = (
                Version(
                    model_version=numeric,
                    ranker=bundle.ranker,
                    snapshot_id=bundle.snapshot,
                    build_id=manifest["build_id"],
                    model_revision=manifest["revision"],
                    git_revision=manifest["git_revision"],
                ),
                bundle,
            )
            info.labels(numeric, bundle.ranker).set(1)
            reports = read_json(bundle.root / "normalization.json")
            pages = read_json(bundle.root / "snapshot.json")["pages"]
            for source in SOURCES:
                summary = reports["sources"].get(source, {})
                records.labels(source).set(summary.get("accepted", 0))
                rejected.labels(source).set(summary.get("rejected", 0))
                timestamps = [
                    datetime.fromisoformat(p["retrieved_at"]).timestamp()
                    for p in pages
                    if p["source"] == source
                ]
                if timestamps:
                    freshness.labels(source).set(max(timestamps))
                docs = [
                    doc
                    for corpus in bundle.docs.values()
                    for doc in corpus
                    if doc.provenance.source == source
                ]
                for field, flag in (
                    ("description", ("description_unknown", "objective_unknown")),
                    ("bbox", ("bbox_unknown",)),
                    ("time", ("temporal_unknown",)),
                    ("resolution", ("resolution_unknown",)),
                ):
                    missing.labels(source, field).set(
                        sum(
                            any(value in doc.metadata_quality_flags for value in flag)
                            for doc in docs
                        )
                    )
        except Exception:
            app.state.model = None
            LOG.exception("Could not load champion from the local registry")
        yield

    app = FastAPI(title="EUPolicyEO", lifespan=lifespan)

    @app.middleware("http")
    async def monitor(request: Request, call_next):
        start = perf_counter()
        if request.method == "POST":
            header = request.headers.get("content-length")
            if header and (not header.isascii() or not header.isdigit() or int(header) > 16_384):
                return Response(status_code=413)
        response = await call_next(request)
        route = getattr(request.scope.get("route"), "path", "unmatched")
        method = request.method if request.method in METHODS else "OTHER"
        request_count.labels(route, method, f"{response.status_code // 100}xx").inc()
        request_time.labels(route).observe(perf_counter() - start)
        return response

    def loaded() -> tuple[Version, Bundle]:
        if not getattr(app.state, "model", None):
            raise HTTPException(503, "No validated champion is loaded")
        return app.state.model

    def search(bundle: Bundle, query: SearchQuery, *, profile: RetrievalProfile | None = None):
        with retrieval_time.labels(query.corpus, bundle.ranker).time():
            results = bundle.search(query, profile=profile)
        result_count.labels(query.corpus).inc(len(results))
        if results:
            top_score.labels(query.corpus, bundle.ranker).observe(results[0].score)
        return results

    @app.get("/healthz")
    def health():
        return {"alive": True}

    @app.get("/readyz")
    def ready():
        loaded()
        return {"ready": True}

    @app.get("/version")
    def version() -> Version:
        return loaded()[0]

    @app.get("/requirements")
    def requirements(celex: str = "32024R1991", article: str = "20") -> list[Evidence]:
        _, bundle = loaded()
        return [
            Evidence.model_validate(bundle.evidence(req))
            for req in bundle.requirements.values()
            if (bundle.sections[req.section_id].celex, bundle.sections[req.section_id].article)
            == (celex, article)
        ]

    @app.post("/search")
    def query(body: SearchQuery) -> SearchResponse:
        model, bundle = loaded()
        return SearchResponse(**model.model_dump(), results=search(bundle, body))

    @app.post("/recommend")
    def recommend(body: RecommendationQuery) -> Recommendation:
        model, bundle = loaded()
        req = bundle.requirements.get(body.requirement_id)
        if not req:
            raise HTTPException(404, "Requirement not found")
        constraints = body.model_dump(exclude={"requirement_id"})
        return Recommendation(
            **model.model_dump(),
            evidence=Evidence.model_validate(bundle.evidence(req)),
            eo=search(
                bundle,
                SearchQuery(query=req.query[:2000], corpus="eo", **constraints),
                profile=req.search_profile,
            ),
            projects=search(
                bundle,
                SearchQuery(query=req.query[:2000], corpus="projects", top_k=body.top_k),
                profile=req.search_profile,
            ),
        )

    @app.get("/assessments/urban")
    @app.post("/assessments/urban")
    def urban_assessment(scenario: AssessmentScenario = DEFAULT_SCENARIO):
        _, bundle = loaded()
        try:
            return build_assessment(
                bundle.snapshot,
                bundle.requirements.values(),
                bundle.collections.values(),
                scenario=scenario,
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/collections/{collection_id}")
    def collection(collection_id: str) -> EOCollection:
        _, bundle = loaded()
        if collection_id not in bundle.collections:
            raise HTTPException(404, "Collection not found")
        return bundle.collections[collection_id]

    @app.get("/availability")
    def check_availability(
        collection_id: str,
        bbox: str | None = Query(None, max_length=90),
        start: AwareDatetime | None = None,
        end: AwareDatetime | None = None,
    ):
        from .granules import availability

        model, bundle = loaded()
        selected = bundle.collections.get(collection_id)
        if selected is None:
            raise HTTPException(404, "Collection not found")
        try:
            bounds = Constraints(bbox=bbox.split(",") if bbox else None, start=start, end=end)
        except ValidationError as exc:
            raise HTTPException(422, "Invalid spatial or temporal constraints") from exc
        return {**model.model_dump(), **availability(bundle.snapshot, selected, bounds)}

    @app.get("/metrics")
    def scrape():
        path = artifacts() / "last-ingest.json"
        if path.is_file():
            values = read_json(path)
            for name in ("pages", "bytes", "retries", "elapsed_seconds"):
                last.labels(name).set(values[name])
            last.labels("success").set(values["status"] == "success")
        return Response(generate_latest(metrics), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
