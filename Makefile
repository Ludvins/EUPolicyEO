PY = uv run
WEB = npm --prefix web
SNAPSHOT ?=
CORDIS_FILE ?=
VERSION ?=
RELEASE ?= artifacts/pages/local
.PHONY: demo test lint compose-up pages-export pages-build pages-preview pages-test offline-smoke
demo:
	$(PY) eupolicyeo fetch-encoder
	$(PY) python scripts/demo.py $(if $(SNAPSHOT),--snapshot "$(SNAPSHOT)") $(if $(CORDIS_FILE),--cordis-file "$(CORDIS_FILE)")
test:
	$(PY) pytest -q
lint:
	$(PY) ruff check .
	$(PY) ruff format --check .
compose-up:
	docker compose up --build -d
pages-export:
	$(PY) eupolicyeo export-pages --version $(VERSION) --output $(RELEASE)
pages-build:
	$(PY) python scripts/prepare_pages.py --bundle $(RELEASE)
	$(WEB) ci
	$(WEB) run build
	$(PY) python scripts/check_dist.py
pages-preview:
	$(WEB) run preview -- --host 127.0.0.1
pages-test:
	$(WEB) run test
	$(WEB) run test:e2e
offline-smoke:
	$(PY) pytest -q tests/test_pipeline.py
