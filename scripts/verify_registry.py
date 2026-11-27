"""Exercise an existing local registry, restarting a dedicated API per alias."""

import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime
from time import sleep

import httpx

from eupolicyeo.registry import promote
from eupolicyeo.settings import artifacts
from eupolicyeo.storage import write_json

parser = argparse.ArgumentParser()
parser.add_argument("baseline")
parser.add_argument("candidate")
parser.add_argument("--port", type=int, default=8011)
args = parser.parse_args()
root = artifacts()
root.mkdir(parents=True, exist_ok=True)
checks = []


def verify(client: httpx.Client, version: str, action: str) -> None:
    change = promote(version, f"Local API verification: {action}", allow_draft=True)
    with (root / f"api-{action}.log").open("wb") as log:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "eupolicyeo.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        try:
            for _ in range(45):
                if proc.poll() is not None:
                    raise RuntimeError(f"API exited; see {log.name}")
                try:
                    ready = client.get("/readyz")
                    if ready.is_success:
                        break
                except httpx.TransportError:
                    pass
                sleep(1)
            else:
                raise RuntimeError(f"API was not ready; see {log.name}")
            response = client.get("/version").raise_for_status().json()
            assert response["model_version"] == version
            requirements = client.get("/requirements").raise_for_status().json()
            req = next(req for req in requirements if req["requirement"]["id"].endswith(":1:b:r0"))
            requirement_id = req["requirement"]["id"]
            result = (
                client.post("/recommend", json={"requirement_id": requirement_id})
                .raise_for_status()
                .json()
            )
            assert result["model_version"] == version
            assert result["evidence"]["requirement"]["id"] == requirement_id
            eo, projects = result["eo"], result["projects"]
            assert isinstance(eo, list) and isinstance(projects, list)
            invalid = client.post("/search", json={"query": "", "top_k": 999, "corpus": "eo"})
            assert invalid.status_code == 422
            metrics = client.get("/metrics").raise_for_status().text
            for name in (
                "eupolicyeo_model_info",
                'status_class="4xx"',
                "eupolicyeo_retrieval_results_total",
            ):
                assert name in metrics
            (root / f"metrics-{action}.prom").write_text(metrics, encoding="utf-8")
            write_json(root / f"recommend-{action}.json", result)
            checks.append(
                {
                    "action": action,
                    "version": response,
                    "change": change,
                    "eo": eo[0]["id"] if eo else None,
                    "project": projects[0]["id"] if projects else None,
                    "eo_count": len(eo),
                    "project_count": len(projects),
                    "invalid_status": invalid.status_code,
                }
            )
            print(
                action,
                version,
                response["ranker"],
                checks[-1]["eo"],
                checks[-1]["project"],
                flush=True,
            )
        finally:
            proc.terminate()
            proc.wait(timeout=10)


with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=4, trust_env=False) as client:
    verify(client, args.baseline, "baseline")
    try:
        verify(client, args.candidate, "promotion")
    finally:
        verify(client, args.baseline, "rollback")
write_json(root / "api-verification.json", {"at": datetime.now(UTC).isoformat(), "checks": checks})
