# 🕸 Web Scraping Data Pipeline

A fault-tolerant ETL pipeline: polite scraping of several sources, cleaning and validation, and idempotent loading into MySQL.

**Role focus:** Data Engineer · **Stack:** Python, BeautifulSoup, MySQL 8.4, Pydantic, pytest + Hypothesis, cron, GitHub Actions

```mermaid
flowchart LR
  W[Websites] --> F[Fetcher: robots, rate limit, retries] --> X[Extract: BeautifulSoup]
  X --> C[Clean] --> V{Validate}
  V -->|valid| L[(MySQL)]
  V -->|invalid| Q[(Quarantine + reason)]
  L --> A[Analytics SQL]
  R[cron] --> F
```

Design decisions are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Features

- **Fetching:** exponential back-off with full jitter, `Retry-After`, per-host rate limits, robots.txt and crawl delay, size limits.
- **Extraction:** stops on page loops, stays on one site, survives single bad pages, and detects a changed layout instead of loading nothing quietly.
- **Cleaning:** exact prices in pence, Unicode and whitespace repair, duplicate removal. Ambiguous values are rejected, not guessed.
- **Loading:** one transaction per source, upserts, daily price history, and a run log. A run with over 20% rejects loads nothing.
- **Scheduling:** cron script and a MySQL lock, so runs never overlap.

## Measured on a live run (24 November 2026)

From [books.toscrape.com](https://books.toscrape.com) and [quotes.toscrape.com](https://quotes.toscrape.com), which exist for scraping practice:

| | Books | Quotes |
|---|---:|---:|
| Pages | 81 | 10 |
| Records loaded | 1,000 | 100 |
| Rejected | 0 | 0 |

Both took 52 seconds in total at 2 requests per second. An earlier run rejected one book whose ID was longer than its column. The quarantine table showed why, and the column was widened.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```
```bash
.venv/bin/harvest run --dry-run
```

With a database:

```bash
export HARVEST_MYSQL_URL='mysql://user:password@localhost:3306/harvest'
```
```bash
.venv/bin/harvest migrate
```
```bash
.venv/bin/harvest --verbose run
```

To schedule it, see [scripts/crontab.example](scripts/crontab.example). Example queries are in [schema/analytics.sql](schema/analytics.sql).

## Tests

70 tests against a local website with injected faults and a real MySQL server:

```bash
scripts/test_mysql.sh
```

This starts a throwaway MySQL server and deletes it afterwards. Plain `pytest` skips the database tests. CI runs everything against MySQL 8.4.

## License

MIT
