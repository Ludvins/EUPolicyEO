import json
import platform
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import httpx
import typer

from .bundle import Bundle, build
from .encoder import MODEL, PINNED_HASHES, REVISION
from .normalization import normalize
from .requirements import extract_snapshot
from .settings import Config, artifacts
from .sources import ingest
from .storage import file_hash, read_json, snapshot_dir, write_json

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)


def emit(value) -> None:
    typer.echo(json.dumps(value, indent=2, ensure_ascii=True))


@app.command()
def doctor():
    root = artifacts()
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=root):
        pass
    emit(
        {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "artifacts": str(root),
            "docker": shutil.which("docker"),
            "node": shutil.which("node"),
            "encoder_cached": all(
                (root / "encoders" / REVISION / name).is_file() for name in PINNED_HASHES
            ),
        }
    )


@app.command("fetch-encoder")
def fetch_encoder():
    root = artifacts() / "encoders" / REVISION
    root.mkdir(parents=True, exist_ok=True)
    hosts = {
        "huggingface.co",
        "cas-bridge.xethub.hf.co",
        "cdn-lfs.huggingface.co",
        "cdn-lfs-us-1.huggingface.co",
        "cdn-lfs-eu-1.huggingface.co",
        "us.aws.cdn.hf.co",
    }
    with TemporaryDirectory(dir=root) as scratch, httpx.Client(timeout=40) as client:
        for name, sha in PINNED_HASHES.items():
            final = root / name
            if final.exists() and file_hash(final) == sha:
                continue
            sub = "onnx/" if name.endswith(".onnx") else ""
            url = f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{sub}{name}"
            temporary = Path(scratch) / name
            for _ in range(6):
                parts = urlsplit(url)
                if parts.scheme != "https" or parts.netloc not in hosts:
                    raise ValueError("unexpected model download redirect")
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = (
                            str(response.next_request.url)
                            if response.next_request
                            else response.headers["location"]
                        )
                        continue
                    response.raise_for_status()
                    with temporary.open("wb") as stream:
                        for chunk in response.iter_bytes():
                            stream.write(chunk)
                            if stream.tell() > 95_000_000:
                                raise ValueError("model artifact exceeds download budget")
                    break
            if not temporary.exists() or file_hash(temporary) != sha:
                raise ValueError(f"pinned encoder checksum mismatch: {name}")
            temporary.replace(final)
    emit({"encoder": MODEL, "revision": REVISION, "files": PINNED_HASHES})


@app.command("ingest")
def ingest_cmd(
    config: Path = typer.Option(Path("configs/demo.yaml")),
    cordis_file: Path | None = None,
    cellar_file: Path | None = None,
    cordis_revision: str | None = None,
    offline: bool = False,
    snapshot: str | None = None,
):
    if offline:
        if not snapshot or cordis_file or cellar_file:
            raise typer.BadParameter("--offline requires --snapshot and accepts no import files")
        emit(normalize(snapshot))
        return
    if snapshot:
        raise typer.BadParameter("--snapshot is used with --offline")
    result = ingest(Config.read(config), cordis_file, cellar_file, cordis_revision)
    emit(
        {
            "snapshot_id": result.snapshot_id,
            "status": result.status,
            "error": result.error,
            **result.summary,
        }
    )
    if result.status != "success":
        raise typer.Exit(1)


@app.command("normalize")
def normalize_cmd(snapshot: str = typer.Option(...)):
    emit(normalize(snapshot))


@app.command("extract")
def extract_cmd(snapshot: str = typer.Option(...)):
    emit({"snapshot_id": snapshot, "requirements": len(extract_snapshot(snapshot))})


@app.command("assess-urban")
def assess_urban_cmd(
    snapshot: str = typer.Option(...), output: Path | None = None, scenario: Path | None = None
):
    from .schemas import EOCollection, MonitoringRequirement
    from .suitability import DEFAULT_SCENARIO, AssessmentScenario, build_assessment

    root = snapshot_dir(snapshot)
    result = build_assessment(
        snapshot,
        map(MonitoringRequirement.model_validate, read_json(root / "requirements.json")),
        map(EOCollection.model_validate, read_json(root / "collections.json")),
        scenario=AssessmentScenario.model_validate(read_json(scenario))
        if scenario
        else DEFAULT_SCENARIO,
    )
    if output:
        write_json(output, result)
    emit(result)


@app.command("resolve-inventory")
def resolve_inventory_cmd(
    snapshot: str = typer.Option(...),
    output: Path | None = None,
    model: str | None = None,
    ollama_url: str = "http://127.0.0.1:11434",
    expected_digest: str | None = None,
    review_limit: int = 3,
):
    from .entity_resolution import llm_adjudicator, resolve_snapshot

    if model:
        from .generation import Ollama

        with Ollama(model=model, url=ollama_url, expected_digest=expected_digest) as engine:
            result = resolve_snapshot(
                snapshot, adjudicator=llm_adjudicator(engine), review_limit=review_limit
            )
    else:
        result = resolve_snapshot(snapshot, review_limit=review_limit)
    if output:
        write_json(output, result)
    emit(result)


@app.command("compare-inventory")
def compare_inventory_cmd(previous: str, current: str, output: Path | None = None):
    from .entity_resolution import compare_snapshots

    result = compare_snapshots(previous, current)
    if output:
        write_json(output, result)
    emit(result)


@app.command("refresh-inventory")
def refresh_inventory_cmd(
    previous: str = typer.Option(...), config: Path | None = None, output: Path | None = None
):
    from .entity_resolution import refresh_snapshot

    result = refresh_snapshot(previous, Config.read(config) if config else None)
    if output:
        write_json(output, result)
    emit(result)
    if result["status"] != "success":
        raise typer.Exit(1)


@app.command("extract-with-llm")
def extract_with_llm_cmd(
    snapshot: str = typer.Option(...),
    section: list[str] = typer.Option(...),
    model: str = "qwen3.5:9b",
    ollama_url: str = "http://127.0.0.1:11434",
    expected_digest: str | None = None,
    output: Path | None = None,
):
    from .generation import Ollama, extract_legal, load_legal_sections

    with Ollama(model=model, url=ollama_url, expected_digest=expected_digest) as engine:
        result = extract_legal(load_legal_sections(snapshot), section, engine)
    if output:
        write_json(output, result)
    emit(result)


@app.command("evidence-brief")
def evidence_brief_cmd(
    assessment: Path = typer.Option(...),
    question: str = typer.Option(...),
    model: str = "qwen3.5:9b",
    ollama_url: str = "http://127.0.0.1:11434",
    expected_digest: str | None = None,
    output: Path | None = None,
):
    from .generation import Ollama, assessment_sources, generate_brief
    from .storage import digest, json_bytes

    matrix = read_json(assessment)
    assessment_id = matrix.get("assessment_id")
    payload = {key: value for key, value in matrix.items() if key != "assessment_id"}
    if assessment_id != digest(json_bytes(payload))[:24]:
        raise typer.BadParameter("assessment checksum differs from its content")
    with Ollama(model=model, url=ollama_url, expected_digest=expected_digest) as engine:
        result = generate_brief(question, assessment_sources(matrix), engine)
    result["assessment_id"] = assessment_id
    if output:
        write_json(output, result)
    emit(result)


@app.command("discover")
def discover_cmd(
    snapshot: str = typer.Option(...),
    query: str = typer.Option(...),
    corpus: str = "eo",
    top_k: int = 5,
    browser_release: Path | None = None,
):
    from .bundle import CORPORA
    from .discovery import DiscoveryIndex
    from .encoder import Encoder
    from .measurements import catalogue_measurements
    from .retrieval import hydrate
    from .schemas import SearchQuery

    request = SearchQuery(query=query, corpus=corpus, top_k=top_k)
    root = snapshot_dir(snapshot)
    filename = f"{CORPORA[request.corpus]}.json"
    records = hydrate(read_json(root / filename), request.corpus)
    if browser_release:
        if read_json(browser_release / "manifest.json")["parent_snapshot_id"] != snapshot:
            raise typer.BadParameter("browser release does not match snapshot")
        ids = {row["id"] for row in read_json(browser_release / filename)}
        records = [row for row in records if row.id in ids]
    encoder = Encoder(artifacts() / "encoders" / REVISION)
    emit(DiscoveryIndex(records, catalogue_measurements(root), encoder).search(request))


@app.command("build-index")
def build_cmd(snapshot: str = typer.Option(...), ranker: str = "bm25"):
    emit(build(snapshot, ranker).manifest)


@app.command("annotation-pool")
def pool_cmd(snapshot: str = typer.Option(...), output: Path = Path("artifacts/annotation")):
    from .evaluation import annotation_pool

    emit(annotation_pool([build(snapshot, ranker) for ranker in ("bm25", "dense")], output))


@app.command("evaluate")
def evaluate_cmd(
    snapshot: str = typer.Option(...),
    ranker: str = "bm25",
    annotations: Path = Path("artifacts/annotation"),
):
    from .evaluation import evaluate

    emit(evaluate(build(snapshot, ranker), annotations))


@app.command("benchmark")
def benchmark_cmd(
    snapshot: str = typer.Option(...),
    ranker: str = "bm25",
    repeats: int = typer.Option(3, min=2, max=20),
    bundle: Path | None = None,
):
    from .evaluation import benchmark

    emit(benchmark(Bundle(bundle) if bundle else build(snapshot, ranker), repeats))


@app.command("register")
def register_cmd(
    snapshot: str = typer.Option(...),
    ranker: str = "bm25",
    annotations: Path = Path("artifacts/annotation"),
    bundle: Path | None = None,
):
    from .evaluation import evaluate
    from .registry import register

    model = Bundle(bundle) if bundle else build(snapshot, ranker)
    if model.snapshot != snapshot or model.ranker != ranker:
        raise typer.BadParameter("selected bundle snapshot or ranker differs from options")
    report = evaluate(model, annotations) if (annotations / "queries.jsonl").is_file() else None
    emit({"version": register(model, report), "ranker": ranker, "snapshot_id": snapshot})


@app.command("promote")
def promote_cmd(
    version: str = typer.Option(...), reason: str = typer.Option(...), allow_draft: bool = False
):
    from .registry import promote

    emit(promote(version, reason, allow_draft))


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, model_version: str | None = None):
    import uvicorn

    if model_version is None:
        uvicorn.run("eupolicyeo.api:app", host=host, port=port)
        return
    from .api import create_app
    from .registry import load

    if not model_version.isdecimal():
        raise typer.BadParameter("provide an exact numeric registry version")
    uvicorn.run(create_app(lambda: load(model_version)), host=host, port=port)


@app.command("export-pages")
def export_cmd(
    version: str = typer.Option(...),
    output: Path = typer.Option(...),
    config: Path = Path("configs/pages.yaml"),
    dense_version: str | None = None,
):
    from .publication import PagesConfig, export
    from .registry import load

    if not version.isdecimal() or (dense_version and not dense_version.isdecimal()):
        raise typer.BadParameter("provide exact numeric registry versions")
    numeric, bundle, _ = load(version)
    dense = load(dense_version)[1] if dense_version else None
    emit(export(bundle, numeric, PagesConfig.read(config), output, dense))


@app.command("validate-pages")
def validate_cmd(bundle: Path = typer.Option(...)):
    from .publication import validate

    manifest = validate(bundle)
    emit(
        {
            "release_id": manifest["release_id"],
            "registry_version": manifest["registry_version"],
            "counts": manifest["source_counts"],
            "assets": len(manifest["assets"]),
        }
    )


@app.command("query-parquet")
def parquet_cmd(snapshot: str = typer.Option(...)):
    import duckdb

    from .storage import snapshot_dir

    root = snapshot_dir(snapshot)
    with duckdb.connect(":memory:") as connection:
        summary = {
            name: connection.execute(
                "select count(*), count(distinct id) from read_parquet(?)",
                [str(root / f"{name}.parquet")],
            ).fetchone()
            for name in ("sections", "requirements", "projects", "collections")
        }
    emit({key: {"total": value[0], "unique": value[1]} for key, value in summary.items()})


@app.command("ingest-granules")
def granules_cmd(
    snapshot: str = typer.Option(...),
    collection: list[str] = typer.Option(...),
    bbox: str = typer.Option(...),
    start: str = typer.Option(...),
    end: str = typer.Option(...),
    pages: int = typer.Option(3, min=1, max=100),
    page_size: int = typer.Option(50, min=1, max=100),
):
    from .granules import inventory
    from .schemas import Constraints

    bounds = Constraints(bbox=bbox.split(","), start=start, end=end)
    report = inventory(snapshot, collection, bounds, pages, page_size)
    emit({k: v for k, v in report.items() if k != "raw_pages"})
    if report["status"] != "success":
        raise typer.Exit(1)
