FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home candid && mkdir /data && chown candid /data
USER candid
ENV CANDID_ENV=production DATABASE_URL=sqlite:////data/candid.db FLASK_APP=candid:create_app
EXPOSE 8000
# SECRET_KEY must be supplied. Instance files live in /data.
CMD ["sh", "-c", "flask db upgrade && gunicorn --bind 0.0.0.0:8000 --workers 1 --threads 4 'candid:create_app()'"]
