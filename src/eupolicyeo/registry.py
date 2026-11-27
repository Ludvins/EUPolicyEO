import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import mlflow
import pandas as pd
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException
from mlflow.models import Model
from mlflow.models.signature import infer_signature

from .bundle import Bundle
from .settings import artifacts, tracking_uri
from .storage import read_json, write_json

NAME = "eupolicyeo-ranker"
EXPERIMENT = "eupolicyeo-retrieval"


def client() -> MlflowClient:
    uri = tracking_uri()
    mlflow.set_tracking_uri(uri)
    mlflow.set_registry_uri(uri)
    return MlflowClient(tracking_uri=uri, registry_uri=uri)


def register(bundle: Bundle, evaluation: dict | None = None) -> str:
    registry = client()
    mlflow.set_experiment(EXPERIMENT)
    bundle.smoke()
    corpus = "eo"
    example = pd.DataFrame([{"query": bundle.docs[corpus][0].title, "corpus": corpus, "top_k": 1}])
    from .schemas import SearchQuery

    result = bundle.search(SearchQuery.model_validate(example.iloc[0].to_dict()))
    output = pd.DataFrame(
        {"results_json": [json.dumps([r.model_dump(mode="json") for r in result])]}
    )
    requirements = [
        f"{pkg}=={version(pkg)}"
        for pkg in (
            "mlflow",
            "pandas",
            "numpy",
            "pydantic",
            "onnxruntime",
            "tokenizers",
            "pyarrow",
            "pyyaml",
        )
    ]
    with mlflow.start_run() as run:
        mlflow.log_params(
            {
                k: bundle.manifest[k]
                for k in (
                    "ranker",
                    "snapshot_id",
                    "build_id",
                    "tokenizer",
                    "revision",
                    "git_revision",
                )
            }
        )
        mlflow.log_params(bundle.manifest["counts"])
        mlflow.log_dict(bundle.manifest, "manifest.json")
        mlflow.log_dict(output.iloc[0].to_dict(), "sample.json")
        if evaluation:
            mlflow.log_dict(evaluation, "evaluation.json")
            for corpus, summary in evaluation["corpora"].items():
                mlflow.log_metrics(
                    {f"{corpus}.{metric}": value for metric, value in summary["mean"].items()}
                )
        status = (
            "reviewed"
            if evaluation and any(c["query_count"] for c in evaluation["corpora"].values())
            else "draft"
        )
        mlflow.set_tag("evaluation_status", status)
        package = Path(__file__).parent
        with TemporaryDirectory() as temporary:
            model_dir = Path(temporary) / "ranker"
            entry = package / "pyfunc_model.py"
            mlflow.pyfunc.save_model(
                path=str(model_dir),
                python_model=str(entry),
                artifacts={"bundle": str(bundle.root)},
                code_paths=[str(package)],
                signature=infer_signature(example, output),
                input_example=example,
                pip_requirements=requirements,
            )
            manifest_path = model_dir / "MLmodel"
            artifact = Model.load(str(manifest_path))
            # Models from code only need the copied script's basename at load time.
            # A Windows absolute source path cannot be resolved in a Linux container.
            artifact.flavors["python_function"]["model_code_path"] = entry.name
            artifact.save(str(manifest_path))
            mlflow.log_artifacts(str(model_dir), artifact_path="ranker")
        registered = mlflow.register_model(
            f"runs:/{run.info.run_id}/ranker",
            NAME,
            tags={
                "ranker": bundle.ranker,
                "snapshot_id": bundle.snapshot,
                "build_id": bundle.manifest["build_id"],
                "review": status,
                "run_id": run.info.run_id,
            },
        )
    registry.set_registered_model_alias(NAME, "candidate", registered.version)
    return str(registered.version)


def load(model_version: str | None = None):
    registry = client()
    selected = (
        registry.get_model_version(NAME, str(model_version))
        if model_version
        else registry.get_model_version_by_alias(NAME, "champion")
    )
    model = mlflow.pyfunc.load_model(f"models:/{NAME}/{selected.version}")
    implementation = model.unwrap_python_model()
    bundle = implementation.bundle
    if (
        selected.tags.get("snapshot_id") != bundle.snapshot
        or selected.tags.get("build_id") != bundle.manifest["build_id"]
    ):
        raise ValueError("registry lineage differs from model artifact")
    return str(selected.version), bundle, model


def promote(model_version: str, reason: str, allow_draft: bool) -> dict:
    registry = client()
    selected = registry.get_model_version(NAME, model_version)
    if selected.tags.get("review") != "reviewed" and not allow_draft:
        raise ValueError("draft model promotion requires --allow-draft")
    version_id, bundle, model = load(model_version)
    bundle.smoke()
    result = model.predict(
        pd.DataFrame(
            [
                {
                    "query": bundle.docs["eo"][0].title,
                    "corpus": "eo",
                    "top_k": 1,
                }
            ]
        )
    )
    if not json.loads(result.iloc[0]["results_json"]):
        raise ValueError("packaged pyfunc smoke returned no results")
    try:
        previous = registry.get_model_version_by_alias(NAME, "champion").version
    except MlflowException as exc:
        if exc.error_code not in {"RESOURCE_DOES_NOT_EXIST", "INVALID_PARAMETER_VALUE"}:
            raise
        previous = None
    registry.set_registered_model_alias(NAME, "champion", version_id)
    change = {
        "version": version_id,
        "previous": previous,
        "reason": reason,
        "snapshot_id": bundle.snapshot,
        "ranker": bundle.ranker,
        "review": selected.tags.get("review"),
        "at": datetime.now(UTC).isoformat(),
    }
    path = artifacts() / "promotions.json"
    write_json(path, [*(read_json(path) if path.exists() else []), change])
    return change
