.PHONY: install test lint format db demo eval trace docker clean

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

db:  ## generate the 200k-booking SQLite warehouse
	hotel-agent init-db

demo:  ## offline: scripted model, real tools and database
	hotel-agent ask --demo
	hotel-agent ask --demo --scenario recover_bad_column
	hotel-agent ask --demo --scenario injection_in_data

eval:
	hotel-agent eval --compare-naive

trace:
	hotel-agent trace-html --out trace.html

docker:
	docker build -t hotel-revenue-sql-agent .

clean:
	rm -rf data/*.db traces reports/*.md trace.html .pytest_cache .ruff_cache .hypothesis
bench:
	hotel-agent bench
