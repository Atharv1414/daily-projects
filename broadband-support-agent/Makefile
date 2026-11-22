.PHONY: install test lint format demo eval seed docker

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

demo:
	support-agent run --demo --trace-html reports/demo_trace.html

eval:
	support-agent eval --demo

seed:
	support-agent seed

docker:
	docker build -t broadband-support-agent .
