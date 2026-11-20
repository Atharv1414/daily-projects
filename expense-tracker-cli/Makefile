.PHONY: install test lint format coverage demo bench docker clean

install:  ## install in editable mode with dev tools
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

coverage:
	pytest --cov=expense_tracker --cov-report=term-missing

demo:  ## generate sample statements, import them and print reports
	EXPENSE_DB=demo.db expense generate-data data
	EXPENSE_DB=demo.db expense import data/bank_a_statement.csv --quarantine data/rejected.csv
	EXPENSE_DB=demo.db expense import data/bank_b_statement.csv
	EXPENSE_DB=demo.db expense budget food 450 --month 2026-10
	EXPENSE_DB=demo.db expense summary --month 2026-10
	EXPENSE_DB=demo.db expense anomalies
	EXPENSE_DB=demo.db expense report report.html --month 2026-10

bench:
	expense bench --rows 100000

docker:
	docker build -t expense-tracker .

clean:
	rm -rf demo.db* data report.html .pytest_cache .ruff_cache .coverage
