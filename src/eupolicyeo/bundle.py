import platform
import shutil
import subprocess
from pathlib import Path
from tempfile import mkdtemp
from time import perf_counter

import numpy as np

from .encoder import DIMENSION, MODEL, REVISION, Encoder
from .retrieval import (
    FREE_TEXT_POLICIES,
    FREE_TEXT_POLICY,
    TOKENIZER,
    bm25,
    document_text,
    evidence_forms,
    hydrate,
    lexical_index,
    rank,
    supported_rows,
    with_topic_evidence,
)
from .schemas import LegalSection, MonitoringRequirement, RetrievalProfile, SearchQuery
from .settings import Config, artifacts
from .storage import digest, file_hash, json_bytes, read_json, snapshot_dir, write_json

CORPORA = {"eo": "collections", "projects": "projects"}
ASSETS = {
    "collections.json",
    "projects.json",
    "sections.json",
    "requirements.json",
    "snapshot.json",
    "normalization.json",
}


def code_revision() -> str | None:
    source = Path(__file__).resolve()
    root = source.parents[2]

    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", "--no-optional-locks", *args],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()

    try:
        if Path(git("rev-parse", "--show-toplevel")).resolve() != root:
            return None
        git("ls-files", "--error-unmatch", "--", source.relative_to(root).as_posix())
        if git("status", "--porcelain=v1", "--untracked-files=all"):
            return None
        return git("rev-parse", "HEAD")
    except (subprocess.SubprocessError, OSError):
        return None


def implementation_id() -> str:
    root = Path(__file__).parent
    return digest(json_bytes({f.name: file_hash(f) for f in sorted(root.glob("*.py"))}))


class Bundle:
    def __init__(self, root: Path, load_encoder=True):
        self.root = root
        self.manifest = read_json(root / "manifest.json")
        self.snapshot = self.manifest["snapshot_id"]
        self.ranker = self.manifest["ranker"]
        expected = ASSETS | (
            {"eo.index.json", "projects.index.json"}
            if self.ranker == "bm25"
            else {
                "eo.npy",
                "projects.npy",
                "encoder/model.onnx",
                "encoder/tokenizer.json",
                "encoder/tokenizer_config.json",
            }
        )
        if self.ranker not in {"bm25", "dense"} or self.manifest["schema_version"] != 1:
            raise ValueError("unsupported model schema or ranker")
        if set(self.manifest["files"]) != expected:
            raise ValueError("model file inventory mismatch")
        for name, sha in self.manifest["files"].items():
            if file_hash(root / name) != sha:
                raise ValueError(f"model hash mismatch: {name}")
        source = read_json(root / "snapshot.json")
        if source["snapshot_id"] != self.snapshot or source["status"] != "success":
            raise ValueError("model snapshot mismatch")
        self.docs = {
            key: hydrate(read_json(root / f"{file}.json"), key) for key, file in CORPORA.items()
        }
        self.collections = {d.id: d for d in self.docs["eo"]}
        self.sections = {
            s.id: s for s in map(LegalSection.model_validate, read_json(root / "sections.json"))
        }
        self.requirements = {
            r.id: r
            for r in map(
                MonitoringRequirement.model_validate, read_json(root / "requirements.json")
            )
        }
        for corpus, docs in self.docs.items():
            if [doc.id for doc in docs] != sorted(set(doc.id for doc in docs)):
                raise ValueError("model corpus must have unique sorted IDs")
            if len(docs) != self.manifest["counts"][corpus]:
                raise ValueError("corpus count differs from model manifest")
            if any(doc.provenance.snapshot_id != self.snapshot for doc in docs):
                raise ValueError("document snapshot mismatch")
        for req in self.requirements.values():
            section = self.sections[req.section_id]
            if section.text[req.evidence_start : req.evidence_end] != req.verbatim_evidence:
                raise ValueError("requirement evidence span mismatch")
            if req.parent_section_id:
                parent = self.sections[req.parent_section_id]
                if (
                    parent.text[req.parent_evidence_start : req.parent_evidence_end]
                    != req.parent_evidence
                ):
                    raise ValueError("parent evidence span mismatch")
        self.indexes = {}
        self.vectors = {}
        self.scoped_rows = {}
        self.encoder = None
        self.free_text_policy = self.manifest.get("free_text_policy")
        if self.free_text_policy is not None and self.free_text_policy not in FREE_TEXT_POLICIES:
            raise ValueError("unsupported free-text policy")
        if self.ranker == "bm25":
            self.indexes = {c: read_json(root / f"{c}.index.json") for c in CORPORA}
            for key, index in self.indexes.items():
                if (
                    index["ids"] != [d.id for d in self.docs[key]]
                    or index["tokenizer"] != TOKENIZER
                ):
                    raise ValueError("lexical index alignment mismatch")
        else:
            for key in CORPORA:
                vectors = np.load(root / f"{key}.npy", allow_pickle=False)
                if (
                    vectors.shape != (len(self.docs[key]), DIMENSION)
                    or not np.isfinite(vectors).all()
                    or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)
                ):
                    raise ValueError("dense vector alignment or normalization mismatch")
                self.vectors[key] = vectors
            if load_encoder:
                self.encoder = Encoder(root / "encoder", self.manifest["encoder_threads"])
                if self.free_text_policy:
                    self.indexes = {key: lexical_index(docs) for key, docs in self.docs.items()}
        self.evidence_forms = (
            {key: evidence_forms(index) for key, index in self.indexes.items()}
            if self.free_text_policy
            else {}
        )

    def search(self, query: SearchQuery, *, profile: RetrievalProfile | None = None):
        corpus = query.corpus
        scoped = None
        if profile is not None:
            if profile.query is None:
                return []
            query = query.model_copy(update={"query": profile.query})
            scope = (corpus, profile.model_dump_json())
            scoped = self.scoped_rows.get(scope)
            if scoped is None:
                docs = self.docs[corpus]
                scoped = tuple(
                    with_topic_evidence(docs, dict.fromkeys(range(len(docs)), 0.0), profile)
                )
                self.scoped_rows[scope] = scoped
            if not scoped:
                return []
        elif self.free_text_policy:
            scoped = supported_rows(
                self.indexes[corpus],
                self.evidence_forms[corpus],
                query.query,
                self.free_text_policy,
            )
            if not scoped:
                return []
        if self.ranker == "bm25":
            scores = bm25(self.indexes[corpus], query.query)
            if scoped is not None:
                documented = profile.record_evidence if profile is not None else {}
                scores = {
                    index: scores.get(index, 0.0)
                    for index in scoped
                    if profile is None
                    or index in scores
                    or self.docs[corpus][index].id in documented
                }
        else:
            vector = self.encoder.encode([query.query])[0]
            if scoped is None:
                scores = dict(enumerate(self.vectors[corpus] @ vector))
            else:
                scores = dict(zip(scoped, self.vectors[corpus][list(scoped)] @ vector, strict=True))
        return rank(
            self.docs[corpus],
            scores,
            query,
            "bm25" if self.ranker == "bm25" else "cosine",
            profile=profile,
        )

    def evidence(self, requirement: MonitoringRequirement) -> dict:
        section = self.sections[requirement.section_id]
        return {
            "requirement": requirement,
            "section": section,
            "parent_section": self.sections.get(requirement.parent_section_id),
        }

    def smoke(self) -> None:
        if not self.requirements:
            raise ValueError("model has no requirements")
        for corpus, docs in self.docs.items():
            if not docs or not self.search(
                SearchQuery(query=docs[0].title[:2000], corpus=corpus, top_k=1)
            ):
                raise ValueError(f"model did not return smoke result for {corpus}")


def build(snapshot: str, ranker: str) -> Bundle:
    if ranker not in {"bm25", "dense"}:
        raise ValueError("ranker must be bm25 or dense")
    source = snapshot_dir(snapshot)
    files = sorted(ASSETS)
    metadata = read_json(source / "manifest.json")
    if metadata["status"] != "success":
        raise ValueError("model requires a successful source snapshot")
    cfg = Config.model_validate(metadata["config"])
    implementation = implementation_id()
    source_hashes = {
        name: file_hash(source / ("manifest.json" if name == "snapshot.json" else name))
        for name in files
        if name != "normalization.json"
    }
    build_id = digest(
        json_bytes(
            [
                snapshot,
                ranker,
                implementation,
                source_hashes,
                REVISION if ranker == "dense" else TOKENIZER,
            ]
        )
    )[:24]
    parent = artifacts() / "models" / snapshot
    parent.mkdir(parents=True, exist_ok=True)
    output = parent / build_id
    if output.exists():
        return Bundle(output)
    stage = Path(mkdtemp(dir=parent, prefix=".build-"))
    try:
        started = perf_counter()
        for name in files:
            shutil.copyfile(
                source / ("manifest.json" if name == "snapshot.json" else name), stage / name
            )
        encoder = None
        counts = {}
        if ranker == "dense":
            (stage / "encoder").mkdir()
            for name in ("model.onnx", "tokenizer.json", "tokenizer_config.json"):
                target = f"encoder/{name}"
                shutil.copyfile(artifacts() / "encoders" / REVISION / name, stage / target)
                files.append(target)
            encoder = Encoder(stage / "encoder", cfg.encoder_threads, cfg.encoder_batch)
        embedding_seconds = 0.0
        for corpus, name in CORPORA.items():
            docs = hydrate(read_json(stage / f"{name}.json"), corpus)
            counts[corpus] = len(docs)
            if encoder:
                file = f"{corpus}.npy"
                start_embed = perf_counter()
                np.save(
                    stage / file,
                    encoder.encode([document_text(d) for d in docs]),
                    allow_pickle=False,
                )
                embedding_seconds += perf_counter() - start_embed
            else:
                file = f"{corpus}.index.json"
                write_json(stage / file, lexical_index(docs))
            files.append(file)
        manifest = {
            "schema_version": 1,
            "snapshot_id": snapshot,
            "build_id": build_id,
            "ranker": ranker,
            "counts": counts,
            "git_revision": code_revision(),
            "implementation_hash": implementation,
            "tokenizer": TOKENIZER,
            "free_text_policy": FREE_TEXT_POLICY,
            "encoder": MODEL if encoder else None,
            "revision": REVISION if encoder else None,
            "encoder_threads": cfg.encoder_threads,
            "python": platform.python_version(),
            "build_seconds": round(perf_counter() - started, 4),
            "embedding_seconds": round(embedding_seconds, 4) if encoder else None,
            "files": {name: file_hash(stage / name) for name in files},
        }
        write_json(stage / "manifest.json", manifest)
        Bundle(stage, load_encoder=False)
        stage.rename(output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return Bundle(output)
