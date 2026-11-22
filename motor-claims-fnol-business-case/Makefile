.PHONY: install test lint report summary docker

install:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check .
	ruff format --check .

report:
	fnol-case report

summary:
	fnol-case summary

docker:
	docker build -t motor-claims-fnol-business-case .
