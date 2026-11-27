import re
import shutil
import stat
from collections import Counter
from datetime import UTC, datetime
from itertools import chain, zip_longest
from pathlib import Path, PurePosixPath
from tempfile import mkdtemp
from urllib.parse import urlsplit
from zipfile import ZipFile

import numpy as np
import yaml
from pydantic import BaseModel, Field

from .bundle import CORPORA, Bundle, code_revision
from .discovery_terms import DISCOVERY_TERMS, MAX_DISCOVERY_TERMS, project_discovery_terms
from .encoder import DIMENSION, MAX_TOKENS, MODEL, PINNED_HASHES, REVISION, Encoder
from .evaluation import PROBES
from .evidence_uses import ARTICLE20_EVIDENCE
from .legal_search import ARTICLE20_PROFILES
from .measurements import MEASUREMENT_TERMS, catalogue_measurements, measurement_labels
from .retrieval import (
    FREE_TEXT_POLICIES,
    STOP_WORDS,
    TOKENIZER,
    bm25,
    document_text,
    evidence_forms,
    lexical_index,
    rank,
    supported_rows,
    tokenize,
    with_topic_evidence,
)
from .schemas import (
    EOCollection,
    LegalSection,
    MonitoringRequirement,
    ResearchProject,
    SearchDocument,
    SearchQuery,
)
from .settings import artifacts
from .sources import TERMS
from .storage import digest, file_hash, json_bytes, read_json, snapshot_dir, write_json

BASE = {
    "requirements.json",
    "collections.json",
    "projects.json",
    "lexical/eo.json",
    "lexical/projects.json",
    "lexical/tokenizer.json",
    "lexical/reference.json",
    "licenses.json",
    "reports/ingestion.json",
    "reports/model_lineage.json",
}
DENSE = {
    "models/LICENSE.txt",
    "models/model.onnx",
    "models/tokenizer.json",
    "models/tokenizer_config.json",
    "vectors/eo.f32",
    "vectors/projects.f32",
    "vectors/eo.ids.json",
    "vectors/projects.ids.json",
    "vectors/reference.json",
}
ASSESSMENT_REPORT = "reports/suitability.json"
OPTIONAL = {"reports/benchmark.json", "reports/evaluation.json", ASSESSMENT_REPORT}
SITE_CAP = 150 * 1024**2
APACHE_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
SAFE_ID = re.compile(r"^[a-f0-9]{24}$")
LINK_HOSTS = {
    "eur-lex.europa.eu",
    "cordis.europa.eu",
    "stac.dataspace.copernicus.eu",
    "cmr.earthdata.nasa.gov",
    "land.copernicus.eu",
    "doi.org",
    "earthdata.nasa.gov",
    "www.earthdata.nasa.gov",
}


class PagesConfig(BaseModel, extra="forbid"):
    max_projects: int = Field(1000, ge=1, le=5000)
    max_collections_per_source: int = Field(200, ge=1, le=500)
    max_bytes: int = Field(SITE_CAP, gt=0, le=SITE_CAP)
    include_dense: bool = True
    coverage_per_topic: int = Field(0, ge=0, le=100)
    projects_per_discovery_term: int = Field(0, ge=0, le=20)
    include_measurement_terms: bool = False
    collections_per_measurement: int = Field(0, ge=0, le=10)
    include_suitability: bool = False

    @classmethod
    def read(cls, path: Path):
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def safe_link(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.netloc in LINK_HOSTS


def _public_subset(
    records: list[SearchDocument],
    upstream: dict[str, SearchDocument],
    limit: int,
    coverage_per_topic: int,
    projects_per_discovery_term: int = 0,
    collections_per_measurement: int = 0,
) -> list[SearchDocument]:
    """Reserve bounded topic places while keeping public records in stable ID order."""
    term_quota = projects_per_discovery_term or collections_per_measurement
    if not (coverage_per_topic or term_quota) or len(records) <= limit:
        return records[:limit]

    index = lexical_index(records)
    local_records = [upstream[doc.id] for doc in records]
    topic_rows = []
    for point, definition in ARTICLE20_PROFILES.items() if coverage_per_topic else ():
        evidence = ARTICLE20_EVIDENCE.get(point, {})
        profile = definition.model_copy(update={"record_evidence": evidence})
        scores = bm25(index, profile.query)
        full_public = with_topic_evidence(records, scores, profile)
        anchor_profile = profile.model_copy(update={"evidence_groups": profile.evidence_groups[:1]})
        public_anchor = with_topic_evidence(records, scores, anchor_profile)
        supported_locally = with_topic_evidence(local_records, public_anchor, profile)
        topic_rows.append(
            sorted(
                full_public.keys() | supported_locally.keys(),
                key=lambda i: (
                    records[i].id not in evidence,
                    i not in full_public,
                    -scores.get(i, 0.0),
                    records[i].id,
                ),
            )[:coverage_per_topic]
        )

    method_rows = []
    if term_quota:
        candidates_by_term: dict[str, list[int]] = {}
        for i, record in enumerate(records):
            terms = (
                record.measurement_terms
                if isinstance(record, EOCollection)
                else record.discovery_terms
            )
            for term in terms:
                candidates_by_term.setdefault(term, []).append(i)
        for term, candidates in sorted(candidates_by_term.items()):
            scores = bm25(index, term)
            method_rows.append(
                sorted(candidates, key=lambda i: (-scores.get(i, 0.0), records[i].id))[:term_quota]
            )
    by_topic = (i for group in zip_longest(*topic_rows) for i in group if i is not None)
    by_method = (i for group in zip_longest(*method_rows) for i in group if i is not None)
    selected = list(dict.fromkeys(chain(by_topic, by_method, range(len(records)))))[:limit]
    return [records[i] for i in sorted(selected)]


def public_docs(bundle: Bundle, cfg: PagesConfig):
    # Use factual fields. The bulk archive may include beneficiary-written objectives.
    projects = [
        ResearchProject.model_validate(doc.model_dump()).model_copy(
            update={
                "description": None,
                "keywords": [*([doc.acronym] if doc.acronym else []), *doc.topics],
                "discovery_terms": (
                    project_discovery_terms(doc.description)
                    if cfg.projects_per_discovery_term
                    else []
                ),
                "metadata_quality_flags": ["public_objective_omitted"],
            }
        )
        for doc in (
            bundle.docs["projects"]
            if cfg.coverage_per_topic or cfg.projects_per_discovery_term
            else bundle.docs["projects"][: cfg.max_projects]
        )
    ]
    projects = _public_subset(
        projects,
        {doc.id: doc for doc in bundle.docs["projects"]},
        cfg.max_projects,
        cfg.coverage_per_topic,
        cfg.projects_per_discovery_term,
    )
    by_source = []
    upstream = {doc.id: doc for doc in bundle.docs["eo"]}
    measurements = (
        catalogue_measurements(snapshot_dir(bundle.snapshot))
        if cfg.include_measurement_terms
        else {}
    )
    for source in ("cdse", "cmr"):
        records = []
        for doc in bundle.docs["eo"]:
            if doc.provenance.source != source or doc.use_constraints:
                continue
            if source == "cdse" and not doc.id.startswith("cdse:clms_"):
                continue
            fallback = f"https://cmr.earthdata.nasa.gov/search/collections.umm_json?concept_id={doc.provenance.source_id}"
            src = doc.provenance
            if not safe_link(src.source_url):
                src = src.model_copy(update={"source_url": fallback})
            records.append(
                doc.model_copy(
                    update={
                        "description": None,
                        "access_urls": [],
                        "provenance": src,
                        "keywords": doc.keywords if source == "cmr" else [],
                        "measurement_terms": measurement_labels(measurements, doc.id),
                        "metadata_quality_flags": [
                            *doc.metadata_quality_flags,
                            "public_description_omitted",
                        ],
                    }
                )
            )
        if not records:
            raise ValueError(f"no eligible public collection records for {source}")
        by_source.extend(
            _public_subset(
                records,
                upstream,
                cfg.max_collections_per_source,
                cfg.coverage_per_topic,
                collections_per_measurement=cfg.collections_per_measurement,
            )
        )
    return {"eo": sorted(by_source, key=lambda doc: doc.id), "projects": projects}


def release_basis(manifest: dict) -> dict:
    return {
        key: value for key, value in manifest.items() if key not in {"release_id", "created_at"}
    }


def export(
    bundle: Bundle,
    numeric: str,
    cfg: PagesConfig,
    output: Path,
    encoder_bundle: Bundle | None = None,
) -> dict:
    if not numeric.isdecimal():
        raise ValueError("a numeric MLflow version is required")
    dense = encoder_bundle or bundle
    if cfg.include_dense and (dense.ranker != "dense" or dense.snapshot != bundle.snapshot):
        raise ValueError("dense export requires a verified dense bundle for the same snapshot")
    docs = public_docs(bundle, cfg)
    policy = bundle.manifest.get("free_text_policy")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(mkdtemp(dir=output.parent, prefix=".pages-"))
    try:
        source = read_json(bundle.root / "snapshot.json")
        normalization = read_json(bundle.root / "normalization.json")
        source_summary = {
            key: {
                "pages": len([p for p in source["pages"] if p["source"] == key]),
                "latest": max(p["retrieved_at"] for p in source["pages"] if p["source"] == key),
                "mode": next(p["mode"] for p in source["pages"] if p["source"] == key),
                "bounds": list(
                    dict.fromkeys(p["url"] for p in source["pages"] if p["source"] == key)
                )[:30],
            }
            for key in TERMS
        }
        public_ids = {doc.id for records in docs.values() for doc in records}
        evidence = []
        scoped = {}
        for req in bundle.requirements.values():
            if profile := req.search_profile:
                subset = {
                    id_: use for id_, use in profile.record_evidence.items() if id_ in public_ids
                }
                profile = profile.model_copy(update={"record_evidence": subset})
                req = req.model_copy(update={"search_profile": profile})
                scoped.setdefault(profile.query, req)
            row = bundle.evidence(req)
            evidence.append(
                {key: item.model_dump(mode="json") if item else None for key, item in row.items()}
            )
        write_json(stage / "requirements.json", evidence)
        if cfg.include_suitability:
            from .suitability import build_assessment

            matrix = build_assessment(bundle.snapshot, bundle.requirements.values(), docs["eo"])
            write_json(stage / ASSESSMENT_REPORT, matrix)
        write_json(
            stage / "licenses.json",
            {
                "cellar": {
                    "url": TERMS["cellar"],
                    "credit": "© European Union, EUR-Lex, original act; whitespace normalized.",
                },
                "cordis": {
                    "url": TERMS["cordis"],
                    "credit": (
                        "© European Union, CORDIS grant facts. Controlled discovery terms assigned from objectives."
                        if cfg.projects_per_discovery_term
                        else "© European Union, CORDIS grant facts. Objectives omitted."
                    ),
                },
                "cdse": {
                    "url": "https://land.copernicus.eu/en/data-policy",
                    "credit": (
                        "Generated using European Union’s Copernicus Land Monitoring Service information via CDSE STAC. "
                        "The service is funded by the European Union. Selected catalogue fields normalized."
                    ),
                },
                "cmr": {
                    "url": TERMS["cmr"],
                    "credit": "NASA Earthdata CMR and named providers. Selected catalogue facts; abstracts omitted.",
                },
                "encoder": {
                    "url": f"https://huggingface.co/{MODEL}/tree/{REVISION}",
                    "credit": "Sentence Transformers MiniLM, Apache-2.0.",
                },
            },
        )
        write_json(
            stage / "reports/ingestion.json",
            {
                "measured_at": source["created_at"],
                "scope": "Parent local snapshot",
                "fetch": source["summary"],
                "normalization": normalization,
            },
        )
        report_root = artifacts() / "reports"
        for kind in ("benchmark", "evaluation"):
            path = report_root / f"{bundle.manifest['build_id']}-{kind}.json"
            if path.is_file():
                shutil.copyfile(path, stage / "reports" / f"{kind}.json")
        promotions = artifacts() / "promotions.json"
        events = read_json(promotions) if promotions.is_file() else []
        write_json(
            stage / "reports/model_lineage.json",
            {
                "registry_version": numeric,
                "parent_snapshot": bundle.snapshot,
                "build_id": bundle.manifest["build_id"],
                "parent_ranker": bundle.ranker,
                "promotion_history": [
                    event for event in events if event["snapshot_id"] == bundle.snapshot
                ],
            },
        )
        probes = [q[:2000] for q in PROBES]
        lexical_reference = []
        metadata_probes = [
            {
                "bbox": [-7.5, 36, -1.5, 38.8],
                "start": "2025-01-01T00:00:00Z",
                "strict_metadata": True,
            },
            {"bbox": [175, -25, -170, 25], "strict_metadata": False},
            {"start": "2099-01-01T00:00:00Z", "strict_metadata": True},
        ]
        indexes = {key: lexical_index(values) for key, values in docs.items()}
        forms = {key: evidence_forms(index) for key, index in indexes.items()} if policy else {}
        for corpus, records in docs.items():
            name = CORPORA[corpus]
            write_json(stage / f"{name}.json", [doc.model_dump(mode="json") for doc in records])
            write_json(stage / f"lexical/{corpus}.json", indexes[corpus])
            free_text = [(query, {}, None) for query in probes] + [
                (probes[0], c, None) for c in metadata_probes if corpus == "eo"
            ]
            legal = [(query or req.query, {}, req.search_profile) for query, req in scoped.items()]
            for query, constraints, profile in free_text + legal:
                search = SearchQuery(query=query, corpus=corpus, **constraints)
                scores = bm25(indexes[corpus], query) if profile is None or profile.query else {}
                if profile is not None:
                    scores = with_topic_evidence(records, scores, profile)
                elif policy:
                    scores = {
                        i: scores.get(i, 0.0)
                        for i in supported_rows(indexes[corpus], forms[corpus], query, policy)
                    }
                items = rank(records, scores, search, "bm25", profile=profile)
                lexical_reference.append(
                    {
                        "corpus": corpus,
                        "query": query,
                        "constraints": constraints,
                        **({"profile": profile.model_dump()} if profile is not None else {}),
                        "results": [
                            {"id": r.id, "score": r.score, "compatibility": r.compatibility}
                            for r in items
                        ],
                    }
                )
        write_json(stage / "lexical/reference.json", lexical_reference)
        golden = [
            "CAFÉ ſentinel_2",
            "Regulation (EU) 2024/1991",
            "2025-01-01 3.14 km²",
            "  ",
            "Δάσος et forêt",
        ]
        write_json(
            stage / "lexical/tokenizer.json",
            {
                "name": TOKENIZER,
                "stop_words": sorted(STOP_WORDS),
                "golden": [{"text": text, "tokens": tokenize(text)} for text in golden],
            },
        )
        dense_metadata = None
        if cfg.include_dense:
            (stage / "models").mkdir()
            (stage / "vectors").mkdir()
            shutil.copyfile(
                Path(__file__).with_name("licenses") / "Apache-2.0.txt",
                stage / "models/LICENSE.txt",
            )
            for name in PINNED_HASHES:
                shutil.copyfile(dense.root / "encoder" / name, stage / "models" / name)
            encoder = Encoder(stage / "models", dense.manifest["encoder_threads"])
            reference = [
                {"query": value, "vector": vector.tolist(), "ranks": {}}
                for value, vector in zip(probes, encoder.encode(probes), strict=True)
            ]
            for corpus, records in docs.items():
                vectors = encoder.encode([document_text(doc) for doc in records]).astype("<f4")
                vectors.tofile(stage / "vectors" / f"{corpus}.f32")
                ids = [doc.id for doc in records]
                write_json(stage / "vectors" / f"{corpus}.ids.json", ids)
                for row in reference:
                    scores = vectors @ np.asarray(row["vector"], dtype=np.float32)
                    eligible = (
                        supported_rows(indexes[corpus], forms[corpus], row["query"], policy)
                        if policy
                        else range(len(ids))
                    )
                    positions = sorted(eligible, key=lambda i: (-scores[i], ids[i]))[:10]
                    row["ranks"][corpus] = [ids[i] for i in positions]
            write_json(stage / "vectors/reference.json", reference)
            dense_metadata = {
                "source_build_id": dense.manifest["build_id"],
                "encoder": MODEL,
                "revision": REVISION,
                "dtype": "float32",
                "pooling": "attention-mask mean, L2-normalized",
                "opset": 14,
                "max_tokens": MAX_TOKENS,
                "dimension": DIMENSION,
                "parity_gates": {"min_cosine": 0.99, "mean_top10_overlap": 0.9},
            }
        files = {
            p.relative_to(stage).as_posix(): {"sha256": file_hash(p), "bytes": p.stat().st_size}
            for p in sorted(stage.rglob("*"))
            if p.is_file()
        }
        counts = Counter(doc.provenance.source for values in docs.values() for doc in values)
        counts["cellar"] = len(evidence)
        manifest = {
            "schema_version": 1,
            "registry_version": numeric,
            "parent_ranker": bundle.ranker,
            "parent_snapshot_id": bundle.snapshot,
            "parent_build_id": bundle.manifest["build_id"],
            "public_corpus_hash": digest(
                json_bytes(
                    {
                        p: files[p]["sha256"]
                        for p in ("projects.json", "collections.json", "requirements.json")
                    }
                )
            ),
            "git_revision": code_revision(),
            "source_freshness": source_summary,
            "source_counts": dict(counts),
            "counts": {key: len(values) for key, values in docs.items()},
            "max_bytes": cfg.max_bytes,
            "subset_policy": (
                f"Up to {cfg.coverage_per_topic} places per Article 20 topic within each source cap. "
                "Source-documented uses and public topic matches come first, followed by public topic terms with support in local "
                "metadata. Remaining places follow stable record IDs. Public fields are selected grant "
                "and catalogue facts."
                if cfg.coverage_per_topic
                else "Stable ID caps. Public fields are selected grant and catalogue facts."
            )
            + (
                f" Up to {cfg.projects_per_discovery_term} places per controlled CORDIS discovery term."
                if cfg.projects_per_discovery_term
                else ""
            ),
            "tokenizer": TOKENIZER,
            **({"free_text_policy": policy} if policy else {}),
            "rankers": ["bm25", "dense"] if dense_metadata else ["bm25"],
            "dense": dense_metadata,
            "assets": files,
            "created_at": datetime.now(UTC).isoformat(),
        }
        manifest["release_id"] = digest(json_bytes(release_basis(manifest)))[:24]
        write_json(stage / "manifest.json", manifest)
        validate(stage)
        if output.exists():
            existing = validate(output)
            if existing["release_id"] != manifest["release_id"]:
                raise FileExistsError(f"{output} holds a different immutable release")
            return existing
        stage.rename(output)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def validate(root: Path) -> dict:
    if root.is_symlink() or (root / "manifest.json").is_symlink():
        raise ValueError("symlink in release")
    manifest = read_json(root / "manifest.json")
    expected_id = digest(json_bytes(release_basis(manifest)))[:24]
    if manifest["schema_version"] != 1 or manifest["release_id"] != expected_id:
        raise ValueError("unsupported or inconsistent release manifest")
    policy = manifest.get("free_text_policy")
    if policy is not None and policy not in FREE_TEXT_POLICIES:
        raise ValueError("unsupported public free-text policy")
    assets = manifest["assets"]
    expected = BASE | (DENSE if manifest["dense"] else set())
    if not expected.issubset(assets) or assets.keys() - expected - OPTIONAL:
        raise ValueError("unexpected public asset inventory")
    entries = list(root.rglob("*"))
    actual = {path.relative_to(root).as_posix() for path in entries if path.is_file()}
    if actual != set(assets) | {"manifest.json"} or any(path.is_symlink() for path in entries):
        raise ValueError("unlisted/missing public assets")
    bytes_ = (root / "manifest.json").stat().st_size
    for name, meta in assets.items():
        path = root / name
        size = path.stat().st_size
        bytes_ += size
        if size != meta["bytes"] or file_hash(path) != meta["sha256"]:
            raise ValueError(f"asset hash/length mismatch: {name}")
    if bytes_ > min(SITE_CAP, manifest["max_bytes"]):
        raise ValueError("release exceeds byte budget")
    counts = Counter()
    public_doc_ids: set[str] = set()
    public_collections = []
    for corpus, name in CORPORA.items():
        cls = EOCollection if corpus == "eo" else ResearchProject
        rows = read_json(root / f"{name}.json")
        docs = [cls.model_validate(row) for row in rows]
        if corpus == "eo":
            public_collections = docs
        ids = [row.id for row in docs]
        if ids != sorted(set(ids)) or len(ids) != manifest["counts"][corpus]:
            raise ValueError("release document count/IDs inconsistent")
        public_doc_ids.update(ids)
        for doc in docs:
            prov = doc.provenance
            counts[prov.source] += 1
            if doc.discovery_terms and (
                corpus != "projects"
                or len(doc.discovery_terms) > MAX_DISCOVERY_TERMS
                or doc.discovery_terms != sorted(set(doc.discovery_terms))
                or set(doc.discovery_terms) - DISCOVERY_TERMS
            ):
                raise ValueError("invalid public discovery terms")
            if isinstance(doc, EOCollection) and (
                doc.measurement_terms != sorted(set(doc.measurement_terms))
                or set(doc.measurement_terms) - MEASUREMENT_TERMS
            ):
                raise ValueError("invalid public measurement terms")
            if (
                doc.description
                or not safe_link(prov.source_url)
                or prov.snapshot_id != manifest["parent_snapshot_id"]
                or prov.source not in ({"cdse", "cmr"} if corpus == "eo" else {"cordis"})
                or doc.id != f"{prov.source}:{prov.source_id}"
                or (prov.source == "cdse" and not doc.id.startswith("cdse:clms_"))
                or (isinstance(doc, EOCollection) and (doc.use_constraints or doc.access_urls))
            ):
                raise ValueError("invalid public document or provenance")
        if read_json(root / f"lexical/{corpus}.json") != lexical_index(docs):
            raise ValueError("public index differs from public corpus")
        if manifest["dense"]:
            vector_ids = read_json(root / f"vectors/{corpus}.ids.json")
            vector = np.fromfile(root / f"vectors/{corpus}.f32", dtype="<f4")
            if (
                manifest["dense"]["dimension"] != DIMENSION
                or ids != vector_ids
                or vector.size != len(ids) * DIMENSION
                or not np.isfinite(vector).all()
                or not np.allclose(
                    np.linalg.norm(vector.reshape(-1, DIMENSION), axis=1), 1, atol=1e-5
                )
            ):
                raise ValueError("public vectors are malformed")
    requirements = read_json(root / "requirements.json")
    for row in requirements:
        req = MonitoringRequirement.model_validate(row["requirement"])
        section = LegalSection.model_validate(row["section"])
        if (
            not safe_link(section.provenance.source_url)
            or req.section_id != section.id
            or section.text[req.evidence_start : req.evidence_end] != req.verbatim_evidence
            or section.provenance.snapshot_id != manifest["parent_snapshot_id"]
        ):
            raise ValueError("invalid public legal evidence")
        if req.search_profile is not None and any(
            id_ not in public_doc_ids or not safe_link(use.source_url)
            for id_, use in req.search_profile.record_evidence.items()
        ):
            raise ValueError("invalid public evidence-use source or record")
        if req.parent_section_id:
            parent = LegalSection.model_validate(row["parent_section"])
            if (
                parent.id != req.parent_section_id
                or not safe_link(parent.provenance.source_url)
                or parent.text[req.parent_evidence_start : req.parent_evidence_end]
                != req.parent_evidence
            ):
                raise ValueError("invalid public parent evidence")
    counts["cellar"] = len(requirements)
    if ASSESSMENT_REPORT in assets:
        from .suitability import build_assessment

        expected_assessment = build_assessment(
            manifest["parent_snapshot_id"],
            [MonitoringRequirement.model_validate(row["requirement"]) for row in requirements],
            public_collections,
        )
        if read_json(root / ASSESSMENT_REPORT) != expected_assessment:
            raise ValueError("public suitability assessment differs from source records")
    if dict(counts) != manifest["source_counts"] or not all(counts[key] for key in TERMS):
        raise ValueError("required public source is missing")
    if manifest["dense"] and (
        file_hash(root / "models/LICENSE.txt") != APACHE_SHA256
        or any(file_hash(root / "models" / k) != v for k, v in PINNED_HASHES.items())
    ):
        raise ValueError("public encoder differs from pinned revision")
    return manifest


def unpack(archive: Path, expected_sha256: str, target: Path) -> None:
    if file_hash(archive) != expected_sha256.lower():
        raise ValueError("release archive checksum mismatch")
    allowed = BASE | DENSE | OPTIONAL | {"manifest.json"}
    with ZipFile(archive) as zipped:
        members = zipped.infolist()
        names = [member.filename for member in members]
        if (
            len(set(names)) != len(names)
            or set(names) - allowed
            or sum(member.file_size for member in members) > SITE_CAP
            or any(
                member.is_dir()
                or stat.S_ISLNK(member.external_attr >> 16)
                or PurePosixPath(member.filename).is_absolute()
                for member in members
            )
        ):
            raise ValueError("unsafe public archive")
        for member in members:
            path = target / member.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(member) as source, path.open("xb") as out:
                shutil.copyfileobj(source, out)
    validate(target)


def stage_release(bundle: Path, public: Path, *, git_revision: str | None = None) -> dict:
    manifest = validate(bundle)
    if git_revision is not None and manifest["git_revision"] != git_revision:
        raise ValueError("Release archive was built for a different Git revision")
    releases = public / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    active = manifest["release_id"]
    output = releases / active
    if not output.exists():
        temporary = Path(mkdtemp(dir=releases, prefix=".stage-"))
        try:
            shutil.copytree(bundle, temporary, dirs_exist_ok=True)
            validate(temporary)
            temporary.rename(output)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
    validate(output)
    write_json(
        public / "active.json",
        {"release_id": active, "manifest_sha256": file_hash(output / "manifest.json")},
    )
    for stale in releases.iterdir():
        if (
            stale != output
            and stale.is_dir()
            and not stale.is_symlink()
            and SAFE_ID.fullmatch(stale.name)
        ):
            shutil.rmtree(stale)
    return manifest
