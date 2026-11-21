.PHONY: install test lint format data analysis docker clean

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

data:  ## synthetic PAS extract: 60k patients, 260k appointments
	dna-analysis generate

analysis:  ## clean, test, model, forecast, chart, write FINDINGS.md
	dna-analysis run
	cp reports/FINDINGS.md docs/FINDINGS.md

docker:
	docker build -t nhs-outpatient-dna-analysis .

clean:
	rm -rf data/*.csv reports .pytest_cache .ruff_cache .hypothesis
