.PHONY: install test lint all build validate dashboard charts docker

install:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check .
	ruff format --check .

build:
	bi-mart build

validate:
	bi-mart validate

dashboard:
	bi-mart dashboard

charts:
	bi-mart charts

all: build validate dashboard charts

docker:
	docker build -t grocery-retail-bi-mart .
