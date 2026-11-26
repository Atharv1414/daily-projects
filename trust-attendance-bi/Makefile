.PHONY: install all build test lint dashboard charts bench
install:
	pip install -e ".[dev]"
all:          ## generate data, build the warehouse, charts, dashboard and benchmark
	trust-bi all
build:
	trust-bi build
dashboard:
	trust-bi dashboard
charts:
	trust-bi charts
bench:
	trust-bi bench
lint:
	ruff check . && ruff format --check .
test: lint
	pytest -q
