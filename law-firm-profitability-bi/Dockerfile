FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home app && mkdir data && chown app data
ENV LAWBI_DATABASE=/app/data/law_bi.duckdb
USER app
RUN law-bi build
EXPOSE 8000
CMD ["law-bi", "serve", "--demo", "--host", "0.0.0.0"]
