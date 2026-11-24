.PHONY: install build validate export serve test lint
install:
	pip install -e ".[dev]"
build:
	law-bi build
validate:
	law-bi validate
export:
	law-bi export
serve:
	law-bi serve --demo
test:
	pytest -q
lint:
	ruff check . && ruff format --check .
