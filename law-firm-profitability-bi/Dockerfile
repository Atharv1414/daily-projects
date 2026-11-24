FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home app && chown app /app
USER app
RUN law-bi build
EXPOSE 8000
CMD ["law-bi", "serve", "--demo", "--host", "0.0.0.0"]
