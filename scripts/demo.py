"""Run the real-data pipeline against a local tracking server."""

import argparse
from pathlib import Path

from eupolicyeo.bundle import build
from eupolicyeo.evaluation import annotation_pool, benchmark, evaluate
from eupolicyeo.normalization import normalize
from eupolicyeo.registry import register
from eupolicyeo.requirements import extract_snapshot
from eupolicyeo.settings import Config, artifacts
from eupolicyeo.sources import ingest

parser = argparse.ArgumentParser()
parser.add_argument("--config", type=Path, default=Path("configs/demo.yaml"))
parser.add_argument("--cordis-file", type=Path)
parser.add_argument("--snapshot", help="Replay an existing successful local snapshot")
args = parser.parse_args()
if args.snapshot and args.cordis_file:
    parser.error("--snapshot replays a local snapshot and cannot take a new archive")
snapshot = args.snapshot
if not snapshot:
    manifest = ingest(Config.read(args.config), args.cordis_file)
    if manifest.status != "success":
        raise SystemExit(manifest.error)
    snapshot = manifest.snapshot_id
print(snapshot, normalize(snapshot)["sources"], flush=True)
extract_snapshot(snapshot)
bundles = [build(snapshot, ranker) for ranker in ("bm25", "dense")]
pool = artifacts() / "annotations" / snapshot / bundles[0].manifest["build_id"]
if not pool.exists():
    annotation_pool(bundles, pool)
for bundle in bundles:
    benchmark(bundle, 3)
    print(bundle.ranker, register(bundle, evaluate(bundle, pool)), flush=True)
