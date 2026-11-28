.PHONY: install test lint demo evals seed serve
install:
	pip install -e ".[dev]"
test:
	pytest -q
lint:
	ruff check . && ruff format --check .
demo:
	planning-mcp demo
evals:
	planning-mcp evals --json reports/evals.json
seed:
	planning-mcp seed
serve:
	planning-mcp serve
