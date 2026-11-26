FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . uvicorn
RUN useradd --create-home club
USER club
EXPOSE 8000
# MONGO_URL and FELL_ORGANISER_TOKENS must be provided; without MONGO_URL the app would need
# the mongomock dev dependency, which this image deliberately does not install.
CMD ["uvicorn", "fell_results.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
