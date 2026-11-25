.PHONY: install test lint format run docs

install:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check . && ruff format --check .

format:
	ruff check --fix . && ruff format .

run:
	mortgage-exits run

docs:
	mortgage-exits run --out docs
