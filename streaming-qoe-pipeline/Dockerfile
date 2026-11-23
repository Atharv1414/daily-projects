FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
ENV QOE_LOG_DIR=/data/log QOE_WAREHOUSE_PATH=/data/qoe.duckdb
VOLUME /data
CMD ["sh", "-c", "qoe generate && qoe run && qoe report --charts /data/charts"]
