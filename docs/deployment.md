# Run EUPolicyEO

The [static preview](#preview-the-static-explorer) runs the same browser app intended for GitHub Pages. It searches a prepared release on your device. The [local Python stack](#run-the-python-stack) ingests data, builds those releases and serves its own search API. [Side-by-side comparison](../README.md#browser-explorer-and-local-stack)

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/) for ingestion, indexing and export.
- Docker with [Compose v2](https://docs.docker.com/compose/) for the containerized API, registry and metrics.
- Node.js 24.15.0 and npm for the static explorer. The version is pinned in [`.node-version`](../.node-version).

Run the examples from the checkout root. Commands use Bash unless marked PowerShell. A fresh checkout builds its own snapshots and release archives in the ignored `artifacts/` directory.

## Run the Python stack

### 1. Start the registry

```bash
uv sync --locked
uv run eupolicyeo doctor
docker compose config --quiet
docker compose up --build --wait mlflow
export MLFLOW_TRACKING_URI=http://127.0.0.1:5000
```

The registry stores models and SQLite state in a Docker volume. The API reads local artifacts from `./artifacts` mounted at `/data`. The container uses `http://mlflow:5000` to reach the registry.

On PowerShell, use the following environment settings and substitute `curl.exe` for `curl` in the examples. The remaining `uv`, `docker` and `npm` commands have the same arguments. Assign local PowerShell variables with `$NAME = 'value'`.

```powershell
$env:MLFLOW_TRACKING_URI = 'http://127.0.0.1:5000'
$env:PYTHONUTF8 = '1'
```

If port 5000 is occupied, set `EUPOLICYEO_MLFLOW_PORT=5002` in the shell or Compose `.env` before starting MLflow, then point the host CLI at `http://127.0.0.1:5002`. The container continues to use port 5000. Export `MLFLOW_TRACKING_URI` in the host shell for CLI commands. The checked-in [Compose configuration](../compose.yaml) binds services to loopback.

To run the stack without Docker, start MLflow in its own terminal. After registering and promoting a model, run `uv run eupolicyeo serve` in a second terminal. A host-native Prometheus can scrape `127.0.0.1:8000/metrics`.

```bash
mkdir -p artifacts/mlflow
uv run mlflow server --backend-store-uri sqlite:///artifacts/mlflow/tracking.db --serve-artifacts \
  --artifacts-destination ./artifacts/mlflow/objects --host 127.0.0.1 --port 5000 --workers 1
```

### 2. Build and register a local snapshot

The demo profile bounds the data request. Its first run fetches public source records and a pinned MiniLM encoder. The registry receives a BM25 and a dense bundle with the snapshot and build metadata.

```bash
uv run eupolicyeo fetch-encoder
uv run python scripts/demo.py --config configs/demo.yaml
```

Record the snapshot ID and the numeric BM25 and dense versions printed by the script. These are local identifiers. Use these values for `SNAPSHOT`, `BM25_VERSION` and `DENSE_VERSION` in the following examples.

For a saved [CORDIS Projects CSV ZIP](https://cordis.europa.eu/data/cordis-HORIZONprojects-csv.zip), run the demo with `--cordis-file /path/to/projects.zip`. To include the distribution revision, use the explicit `eupolicyeo ingest --cordis-file /path/to/projects.zip --cordis-revision '<Last-Modified header or release identifier>'` command. Live ingest also accepts `--cellar-file` with an official English XHTML file. The snapshot records the acquisition mode. To replay a successful saved snapshot, run `uv run python scripts/demo.py --snapshot "$SNAPSHOT"`. Use `uv run eupolicyeo ingest --offline --snapshot "$SNAPSHOT"` to replay just normalization.

### 3. Promote and inspect a model

`--allow-draft` opts into local promotion of a candidate bundle. The [model card](model_card.md) describes the evaluation protocol.

```bash
uv run eupolicyeo promote --version "$DENSE_VERSION" --reason 'Local demo candidate' --allow-draft
docker compose up --build --wait api prometheus
curl --fail http://127.0.0.1:8000/readyz
curl --fail http://127.0.0.1:8000/version
curl --fail http://127.0.0.1:8000/metrics
```

Open the [API documentation](http://127.0.0.1:8000/docs) to inspect requests and responses. Open [Prometheus](http://127.0.0.1:9090/) and query `up{job="eupolicyeo"}` after the first scrape. The verified run recorded the returned model version and metrics after promotion, rollback and an invalid request. [Run evidence](verification.md)

To switch back to the baseline, reassign the alias and restart the API.

```bash
uv run eupolicyeo promote --version "$BM25_VERSION" --reason 'Restore demo baseline' --allow-draft
docker compose restart api
docker compose up --wait api
curl --fail http://127.0.0.1:8000/version
```

For a repeatable check, use `uv run python scripts/verify_compose.py "$BM25_VERSION" "$DENSE_VERSION"` on the running Compose stack. It tests baseline → candidate → baseline, API readiness, recommendations and the Prometheus scrape. In native mode, use `uv run python scripts/verify_registry.py "$BM25_VERSION" "$DENSE_VERSION"` to run the API check on loopback port 8011.

Use the matching checkout or container when rolling back both the model bundle and the ranking code. An MLflow alias change selects the model bundle for the running API version. [Registry architecture](architecture.md#registry-api-and-metrics)

### 4. Reproduce the bounded scale run

Start with `uv run eupolicyeo ingest --config configs/benchmark.yaml` and run `normalize`, `extract`, `build-index --ranker bm25` and `benchmark --ranker bm25` with the resulting `--snapshot` on each command. `query-parquet` reports row counts and unique IDs across normalized tables.

Set `SNAPSHOT` to the ID from the completed ingest. The following request uses the bounds of the recorded inventory from snapshot `5ed3d4d678b09a79ad422601`. The two collection records must be present in the chosen snapshot.

```bash
uv run eupolicyeo ingest-granules --snapshot "$SNAPSHOT" \
  --collection cdse:sentinel-2-l2a --collection cmr:C1748066515-LPCLOUD \
  --bbox=-12,34,32,62 --start 2025-01-01T00:00:00Z --end 2025-12-31T23:59:59Z \
  --pages 5 --page-size 50
```

Register and promote a model built from the inventory's snapshot to query `GET /availability`. Pass its version as `--granule-version` to `verify_compose.py` to test the recorded inventory after baseline and candidate verification. Counts describe the inventory's bounds and caps. [Data sources and limits](data_sources.md)

## Preview the static explorer

Use an exact dense registry version to generate a semantic release. Use a new output directory for each release.

```bash
uv run eupolicyeo export-pages --version "$DENSE_VERSION" --output artifacts/pages/from-registry
uv run eupolicyeo validate-pages --bundle artifacts/pages/from-registry
uv run python scripts/prepare_pages.py --bundle artifacts/pages/from-registry
npm --prefix web ci
npm --prefix web test
npm --prefix web run build
uv run python scripts/check_dist.py
npm --prefix web exec -- playwright install chromium
npm --prefix web run test:e2e
npm --prefix web run preview -- --host 127.0.0.1
```

Open the [local browser preview](http://127.0.0.1:4173/EUPolicyEO/). Keep `PAGES_BASE` consistent for the Vite build, Playwright and preview when changing the project path. If port 4173 is already occupied, set `E2E_PORT=4177` for Playwright. On PowerShell, use `$env:E2E_PORT = '4177'`. The explorer uses the staged files and runs queries in the browser.

To reproduce an approved browser release from its archive, stage the downloaded ZIP with the SHA-256 recorded for that release. Then run the npm build and preview commands above. This path needs the matching code checkout, Python and Node.

```bash
uv run python scripts/prepare_pages.py --archive /path/to/eupolicyeo-pages.zip \
  --sha256 "$ARCHIVE_SHA256" --git-revision "$(git rev-parse HEAD)"
```

The verified portfolio bundle in the prepared workspace is `artifacts/policy-assessment/pages-final`. To preview it, substitute that path in `prepare_pages.py` and continue with the web commands. To generate a lexical-only release, copy [`pages.yaml`](../configs/pages.yaml), set `include_dense: false` and pass the copy with `export-pages --config` alongside a BM25 version. For a semantic release built from a BM25 primary version, pass `--dense-version` for the dense bundle from the same snapshot.

The CI workflow runs unit tests and a browser startup smoke check from a fresh checkout. The full browser suite requires a staged release. `check_dist.py` checks the release manifest, asset hashes, build size and distribution inventory. [CI workflow](../.github/workflows/ci.yml) · [Release checks](../reports/release_checks.json)

## Publish after approval

Enable Pages with **GitHub Actions** as the source, use a protected branch and configure the `github-pages` environment to require release approval. The original code uses the MIT License, and the export carries source and model attribution. [License](../LICENSE) · [Data reuse](data_sources.md) · [GitHub Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)

Export and validate the bundle from a clean checkout of the intended Git commit. The exporter records the revision when it can identify a clean source checkout. Earlier unversioned archives can still be staged for local preview.

After approving a release, archive the validated bundle with the exact filename expected by the workflow. The archive command prints the release ID and the SHA-256. On PowerShell, run `Get-FileHash` on the archive to print the checksum.

```bash
PUBLISH_BUNDLE=artifacts/pages/public-release
RELEASE_ARCHIVE=artifacts/pages/release-asset/eupolicyeo-pages.zip
REPO='<owner>/<repo>'
CODE_REF='<protected-branch>'
TAG='<unique-approved-release-tag>'
CODE_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(gh api "repos/$REPO/commits/$CODE_REF" --jq .sha)
[ "$CODE_SHA" = "$REMOTE_SHA" ] || exit 1

mkdir -p "$(dirname "$RELEASE_ARCHIVE")"
uv run eupolicyeo export-pages --version "$DENSE_VERSION" --output "$PUBLISH_BUNDLE" || exit 1
uv run eupolicyeo validate-pages --bundle "$PUBLISH_BUNDLE" || exit 1
uv run python scripts/archive_pages.py "$PUBLISH_BUNDLE" "$RELEASE_ARCHIVE" --git-revision "$CODE_SHA" || exit 1

SHA=$(sha256sum "$RELEASE_ARCHIVE" | cut -d' ' -f1)
[ "$(gh api "repos/$REPO/commits/$CODE_REF" --jq .sha)" = "$CODE_SHA" ] || exit 1

gh release create "$TAG" "$RELEASE_ARCHIVE" --repo "$REPO" --target "$CODE_SHA" --title "$TAG" || exit 1
gh workflow run pages.yml --repo "$REPO" --ref "$CODE_REF" -f release_tag="$TAG" -f archive_sha256="$SHA"
gh run list --repo "$REPO" --workflow pages.yml
```

The workflow checks the release archive checksum and matches its code revision to the deployment commit. It then builds against the configured Pages base path and runs browser tests. On the deployed page, open **Dataset and methodology** to verify the release ID and model lineage. Run a new query and check the source links. Record the verified URL, date, code revision and workflow run. [Publishing workflow](../.github/workflows/pages.yml)

Use a unique tag for each approved archive. Roll back Pages by dispatching the workflow with the previous approved tag and checksum against a matching protected code ref, then verify the displayed release. To roll back locally, stage the earlier archive or bundle and build again. Local API rollback uses the MLflow alias instead.
