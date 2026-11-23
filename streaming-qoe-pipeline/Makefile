.PHONY: install lint test generate run crash-demo report bench all clean

install:
	pip install -e ".[dev]"

lint:
	ruff check . && ruff format --check .

test:
	pytest -q

generate:
	qoe generate --sessions 12000 --seed 7

run:
	qoe run

# Kill the processor mid-stream, then resume: outputs are identical to an uninterrupted run.
crash-demo:
	rm -f data/qoe.duckdb && qoe run --crash-after-polls 23 && qoe run

report:
	qoe report --charts docs/charts

bench:
	qoe bench --intervals 1 5 20 --charts docs/charts

all: generate run report

clean:
	rm -rf data/log data/*.duckdb* .pytest_cache .ruff_cache
