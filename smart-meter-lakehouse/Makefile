.PHONY: install test lint format generate run demo report docker clean

install:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

generate:  ## 1,000 meters x 28 days (~1.4M half-hourly reads)
	meterlake generate

demo: generate  ## two incremental daily runs (one with a flaky API), an idempotent rerun, report
	rm -f data/lakehouse.duckdb*
	meterlake run --through 2026-09-21 --flaky 2
	meterlake run --through 2026-10-12
	meterlake run --through 2026-10-12
	meterlake report

report:
	meterlake report

docker:
	docker build -t smart-meter-lakehouse .

clean:
	rm -rf data/landing data/*.duckdb* reports .pytest_cache .ruff_cache .hypothesis
