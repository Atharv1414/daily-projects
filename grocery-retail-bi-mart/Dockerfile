FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
# Generates sources, builds the warehouse, runs the reconciliation suite and renders dashboards.
CMD ["sh", "-c", "bi-mart build && bi-mart validate && bi-mart dashboard"]
