.PHONY: install api web test contract e2e lint
VENV ?= .venv

install:
	python3 -m venv $(VENV) && $(VENV)/bin/pip install -e "api[dev]"
	cd web && npm ci

api:            ## in-memory API with seeded data on :8000
	cd api && ../$(VENV)/bin/fell-results serve

web:            ## Vite dev server on :5173, proxying /api to :8000
	cd web && npm run dev

contract:       ## re-record contract/examples.json from the seeded API
	cd api && ../$(VENV)/bin/fell-results export-contract

lint:
	cd api && ../$(VENV)/bin/ruff check . && ../$(VENV)/bin/ruff format --check .
	cd web && npm run lint

test: lint
	cd api && ../$(VENV)/bin/pytest -q
	cd web && npm test && npm run build

e2e:
	cd web && npm run e2e
