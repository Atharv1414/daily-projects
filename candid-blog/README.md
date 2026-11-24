# 📝 Candid Blog

A secure full-stack blog: server-rendered pages, a JSON API, three roles and full-text search.

**Role focus:** Software Engineer · **Stack:** Python, Flask, SQLAlchemy 2, SQLite (FTS5), Alembic, bcrypt, pytest, Docker, GitHub Actions

Design decisions are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Features

- **Accounts:** bcrypt passwords (cost 12), sign-in rate limits, sessions that end everywhere when a role changes.
- **Roles:** readers comment, authors manage their own posts, admins manage everything. The last active admin cannot be removed.
- **Posts:** drafts, tags, Markdown, comments, pagination and ranked full-text search with word stemming.
- **REST API** (`/api/v1`): CRUD, search, and bearer tokens stored only as hashes.
- **Security:** CSRF protection, strict Content-Security-Policy with no JavaScript at all, allow-list validation, sanitised Markdown, safe redirects, secure cookies.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```
```bash
export FLASK_APP=candid:create_app
```
```bash
.venv/bin/flask db upgrade
```
```bash
.venv/bin/flask create-user admin admin@example.com --role admin
```
```bash
.venv/bin/flask run
```

In production set `CANDID_ENV=production` and `SECRET_KEY`. The app refuses to start without the key. Set `TRUSTED_PROXIES` if it runs behind a proxy.

## API

| Method | Path | Who |
|---|---|---|
| POST | `/api/v1/tokens` | anyone with a password |
| DELETE | `/api/v1/tokens/current` | token owner |
| GET | `/api/v1/posts?q=&tag=&page=&per_page=` | everyone (drafts: owner and admins) |
| GET | `/api/v1/posts/<slug>` | same |
| POST | `/api/v1/posts` | authors, admins |
| PUT, DELETE | `/api/v1/posts/<slug>` | owner, admins |

## Tests

87 tests, **98% branch coverage** (auth 98%, API 100%). The build fails below 85%.

```bash
.venv/bin/pytest
```

They cover every role against every action, CSRF, open redirects, script injection, search-syntax injection, rate limits, token expiry, error hiding, and that migrations match the models.

## License

MIT
