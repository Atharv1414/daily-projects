# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    EXPENSE_DB=/data/expenses.db EXPENSE_LOG_JSON=1 EXPENSE_LOG_LEVEL=INFO
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home --uid 1000 app && mkdir /data \
    && chown app /data
USER app
VOLUME ["/data"]
ENTRYPOINT ["expense"]
CMD ["--help"]
