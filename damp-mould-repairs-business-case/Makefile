.PHONY: install report test lint
install:
	pip install -e ".[dev]"
report:
	damp-case report
test:
	pytest -q
lint:
	ruff check . && ruff format --check .
