FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
# Offline demo by default; pass -e ANTHROPIC_API_KEY=... and a message for live mode.
ENTRYPOINT ["support-agent"]
CMD ["run", "--demo"]
