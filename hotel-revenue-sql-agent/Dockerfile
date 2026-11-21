# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HOTEL_DB=/data/hotel.db AGENT_TRACES_DIR=/data/traces AGENT_REPORTS_DIR=/data/reports
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home --uid 1000 app \
    && mkdir /data && chown app /data
USER app
VOLUME ["/data"]
# Pass ANTHROPIC_API_KEY at runtime (docker run -e ANTHROPIC_API_KEY ...) for live mode.
ENTRYPOINT ["hotel-agent"]
CMD ["ask", "--demo"]
