# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg \
    METERLAKE_LANDING=/data/landing METERLAKE_DB=/data/lakehouse.duckdb \
    METERLAKE_REPORTS=/data/reports
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home --uid 1000 app \
    && mkdir /data && chown app /data
USER app
VOLUME ["/data"]
ENTRYPOINT ["meterlake"]
CMD ["--help"]
