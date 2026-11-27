.PHONY: install test lint run quick report

install:
	pip install -e ".[dev,torch]"

lint:
	ruff check . && ruff format --check .

test:
	pytest -q

run:            ## the full experiment (about 6 minutes on a laptop CPU)
	energy-triage run

quick:          ## smoke test: tiny model, tiny data
	energy-triage run --quick --out /tmp/energy-triage-quick

report:
	energy-triage report
