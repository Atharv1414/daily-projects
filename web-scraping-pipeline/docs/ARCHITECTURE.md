# Architecture

| Module | Job |
|---|---|
| `http.py` | Fetch politely and retry |
| `extract.py` | HTML to raw records, one class per source |
| `clean.py` | Raw to validated records, or a rejection with reasons |
| `db.py` | Migrations, run log, quarantine, upserts |
| `pipeline.py` | Order the steps and decide succeeded, partial or failed |

## Failure handling

| Failure | Response |
|---|---|
| Timeout, dropped connection, 408, 425, 429, 5xx | Retry up to 5 times |
| 404 or other permanent status | Skip the page, mark the run partial |
| `Retry-After` over 2 minutes | Give up on that page |
| Page layout changed | Stop the source, keep what was read, mark it partial or failed |
| Invalid record | Quarantine the raw record with its reasons |
| Over 20% invalid | Load nothing |
| Database error | Roll back the whole load |
| Process killed | The next run marks the old one failed |
| Overlapping cron run | Second run exits quietly |

## Schema

`category` 1–n `book` 1–n `book_price`, `author` 1–n `quote` n–n `tag`, and `pipeline_run` 1–n `rejected_record`. Third normal form. `(book_id, observed_on)` is the price key, so a re-run corrects today's row. Constraints repeat the Python rules, so no other writer can break them. `ix_price_day` covers price-by-day queries.

## Limits

- Pages are fetched one at a time on purpose, to be polite.
- JavaScript-rendered sites are not supported.
- MySQL commits each DDL statement on its own, so a migration that fails part-way needs fixing by hand.
- Books that vanish from the site are kept, and show an old `last_seen_run`.
