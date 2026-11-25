# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home --uid 1000 app \
    && mkdir /work && chown app /work
USER app
WORKDIR /work
VOLUME ["/work"]
ENTRYPOINT ["mortgage-exits"]
CMD ["run"]
