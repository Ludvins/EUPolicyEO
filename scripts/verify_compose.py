"""Verify the running local Compose stack with pre-registered versions."""

import argparse
import subprocess
from datetime import UTC, datetime
from time import sleep

import httpx

from eupolicyeo.registry import promote
from eupolicyeo.settings import artifacts
from eupolicyeo.storage import write_json

parser = argparse.ArgumentParser()
parser.add_argument("baseline")
parser.add_argument("candidate")
parser.add_argument("--granule-version")
args = parser.parse_args()
app = httpx.Client(base_url="http://127.0.0.1:8000", timeout=5, trust_env=False)
prometheus = httpx.Client(base_url="http://127.0.0.1:9090", timeout=5, trust_env=False)
root = artifacts()
checks = []


def verify(version: str, action: str) -> None:
    promote(version, f"Compose verification: {action}", allow_draft=True)
    subprocess.run(["docker", "compose", "restart", "api"], check=True)
    for _ in range(65):
        try:
            if app.get("/readyz").is_success:
                active = app.get("/version").raise_for_status().json()
                if active["model_version"] == version:
                    break
        except httpx.TransportError:
            pass
        sleep(1)
    else:
        raise RuntimeError(f"Compose never reported ready with version {version}")
    all_reqs = app.get("/requirements").raise_for_status().json()
    selection = next(row for row in all_reqs if row["requirement"]["id"].endswith(":1:b:r0"))
    requirement_id = selection["requirement"]["id"]
    result = (
        app.post("/recommend", json={"requirement_id": requirement_id}).raise_for_status().json()
    )
    assert result["model_version"] == version
    assert result["evidence"]["requirement"]["id"] == requirement_id
    eo, projects = result["eo"], result["projects"]
    assert isinstance(eo, list) and isinstance(projects, list)
    invalid = app.post("/search", json={"query": "", "corpus": "eo"})
    assert invalid.status_code == 422
    metrics = app.get("/metrics").raise_for_status().text
    assert 'status_class="4xx"' in metrics
    assert "eupolicyeo_retrieval_results_total" in metrics
    (root / f"docker-{action}.prom").write_text(metrics, encoding="utf-8")
    checks.append(
        {
            "action": action,
            "version": active,
            "project": projects[0]["id"] if projects else None,
            "eo": eo[0]["id"] if eo else None,
            "eo_count": len(eo),
            "project_count": len(projects),
            "invalid_status": invalid.status_code,
        }
    )
    print(action, active["model_version"], active["ranker"], flush=True)


def query_prometheus(query: str):
    for _ in range(25):
        output = prometheus.get("/api/v1/query", params={"query": query}).raise_for_status().json()
        result = output["data"]["result"]
        if result and float(result[0]["value"][1]) > 0:
            return result
        sleep(1)
    raise RuntimeError(f"Prometheus has no positive series for {query}")


verify(args.baseline, "baseline")
try:
    verify(args.candidate, "promotion")
finally:
    verify(args.baseline, "rollback")
observations = []
if args.granule_version:
    try:
        verify(args.granule_version, "scale")
        for id_ in ("cdse:sentinel-2-l2a", "cmr:C1748066515-LPCLOUD"):
            response = (
                app.get(
                    "/availability",
                    params={
                        "collection_id": id_,
                        "bbox": "-12,34,32,62",
                        "start": "2025-01-01T00:00:00Z",
                        "end": "2025-12-31T23:59:59Z",
                    },
                )
                .raise_for_status()
                .json()
            )
            assert response["status"] == "bounded_inventory" and response["observed_compatible"] > 0
            observations.append(response)
            print(id_, response["observed_compatible"], "compatible", flush=True)
    finally:
        verify(args.baseline, "restore-baseline")

up = query_prometheus('up{job="eupolicyeo"}')
model = query_prometheus(f'eupolicyeo_model_info{{version="{args.baseline}"}}')
reject = query_prometheus('eupolicyeo_http_requests_total{status_class="4xx"}')
targets = prometheus.get("/api/v1/targets").raise_for_status().json()["data"]["activeTargets"]
assert any(t["scrapeUrl"] == "http://api:8000/metrics" and t["health"] == "up" for t in targets)
write_json(
    root / "docker-verification.json",
    {
        "at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "prometheus_up": up,
        "prometheus_model": model,
        "prometheus_invalid_requests": reject,
        "targets": targets,
        "granule_observations": observations,
    },
)
print("Prometheus verified", flush=True)
