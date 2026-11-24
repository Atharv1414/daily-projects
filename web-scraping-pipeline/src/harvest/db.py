"""MySQL loading: migrations, run audit, quarantine and idempotent upserts."""

import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pymysql

from .clean import Book, Quote, Record, Rejected
from .config import mysql_options

LOCK = "harvest_pipeline"
MIGRATIONS = Path("schema")


class AlreadyRunning(Exception):
    pass


class Database:
    def __init__(self, url: str | None = None) -> None:
        self._connection = pymysql.connect(
            **mysql_options(url),
            charset="utf8mb4",
            autocommit=True,
            connect_timeout=10,
            init_command=(
                "SET SESSION sql_mode='STRICT_ALL_TABLES,ONLY_FULL_GROUP_BY,"
                "NO_ENGINE_SUBSTITUTION,ERROR_FOR_DIVISION_BY_ZERO', time_zone='+00:00'"
            ),
        )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def query(self, sql: str, args: Sequence | None = None) -> list[tuple]:
        with self._connection.cursor() as cursor:
            cursor.execute(sql, args)
            return list(cursor.fetchall())

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self._connection.begin()
        try:
            yield
        except BaseException:
            self._connection.rollback()
            raise
        self._connection.commit()

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """A server-side lock, so overlapping cron runs cannot load at the same time."""
        if self.query("SELECT GET_LOCK(%s, 0)", (LOCK,))[0][0] != 1:
            raise AlreadyRunning("another run is in progress")
        try:
            yield
        finally:
            self.query("SELECT RELEASE_LOCK(%s)", (LOCK,))

    def migrate(self, folder: Path = MIGRATIONS) -> list[str]:
        self.query(
            "CREATE TABLE IF NOT EXISTS schema_migration (name VARCHAR(100) PRIMARY KEY, "
            "applied_at DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()))"
        )
        done = {name for (name,) in self.query("SELECT name FROM schema_migration")}
        applied = []
        for path in sorted(folder.glob("[0-9]*.sql")):
            if path.name in done:
                continue
            for statement in statements(path.read_text(encoding="utf-8")):
                self.query(statement)
            self.query("INSERT INTO schema_migration (name) VALUES (%s)", (path.name,))
            applied.append(path.name)
        return applied

    def start_run(self, source: str) -> int:
        # A crash cannot update its own row; the next run (which holds the lock) does.
        self.query(
            "UPDATE pipeline_run SET status='failed', finished_at=UTC_TIMESTAMP(3), "
            "message='process ended unexpectedly' WHERE status='running' AND source=%s",
            (source,),
        )
        with self._connection.cursor() as cursor:
            cursor.execute("INSERT INTO pipeline_run (source) VALUES (%s)", (source,))
            return int(cursor.lastrowid)

    def finish_run(self, run_id: int, status: str, message: str | None = None, **counts) -> None:
        columns = ("pages", "failed_pages", "retries", "loaded", "rejected", "duplicates")
        values = [int(counts.get(c, 0)) for c in columns]
        self.query(
            "UPDATE pipeline_run SET status=%s, message=%s, finished_at=UTC_TIMESTAMP(3), "
            + ", ".join(f"{c}=%s" for c in columns)
            + " WHERE id=%s",
            (status, message[:500] if message else None, *values, run_id),
        )

    def quarantine(self, run_id: int, rejected: list[Rejected]) -> None:
        self._many(
            "INSERT INTO rejected_record (run_id, reason, raw) VALUES (%s, %s, %s)",
            [(run_id, r.reason, json.dumps(r.raw, default=str)) for r in rejected],
        )

    def _many(self, sql: str, rows: list[tuple]) -> None:
        if rows:
            with self._connection.cursor() as cursor:
                cursor.executemany(sql, rows)

    def _ids(self, table: str, column: str, values: set[str]) -> dict[str, int]:
        if not values:
            return {}
        marks = ", ".join(["%s"] * len(values))
        rows = self.query(
            f"SELECT {column}, id FROM {table} WHERE {column} IN ({marks})", sorted(values)
        )
        return dict(rows)

    def _lookup(self, table: str, names: set[str]) -> dict[str, int]:
        """Insert missing names, then return ids. Keys are casefolded, as MySQL compares names."""
        self._many(
            f"INSERT INTO {table} (name) VALUES (%s) ON DUPLICATE KEY UPDATE name = name",
            [(n,) for n in sorted(names)],
        )
        ids = {}
        for name in names:
            ids[name] = self.query(f"SELECT id FROM {table} WHERE name = %s", (name,))[0][0]
        return ids

    def load(self, run_id: int, records: list[Record], today: date) -> None:
        """All or nothing. Running it twice gives the same result as running it once."""
        books = [r for r in records if isinstance(r, Book)]
        quotes = [r for r in records if isinstance(r, Quote)]
        with self.transaction():
            if books:
                self._load_books(run_id, books, today)
            if quotes:
                self._load_quotes(run_id, quotes)

    def _load_books(self, run_id: int, books: list[Book], today: date) -> None:
        categories = self._lookup("category", {b.category for b in books})
        self._many(
            "INSERT INTO book (external_id, title, url, category_id, rating, first_seen_run, "
            "last_seen_run) VALUES (%s, %s, %s, %s, %s, %s, %s) AS new "
            "ON DUPLICATE KEY UPDATE title = new.title, url = new.url, "
            "category_id = new.category_id, rating = new.rating, "
            "last_seen_run = new.last_seen_run",
            [
                (b.external_id, b.title, b.url, categories[b.category], b.rating, run_id, run_id)
                for b in books
            ],
        )
        ids = self._ids("book", "external_id", {b.external_id for b in books})
        self._many(
            "INSERT INTO book_price (book_id, observed_on, price_pence, in_stock) "
            "VALUES (%s, %s, %s, %s) AS new ON DUPLICATE KEY UPDATE "
            "price_pence = new.price_pence, in_stock = new.in_stock",
            [(ids[b.external_id], today, b.price_pence, b.in_stock) for b in books],
        )

    def _load_quotes(self, run_id: int, quotes: list[Quote]) -> None:
        authors = self._lookup("author", {q.author for q in quotes})
        tags = self._lookup("tag", {t for q in quotes for t in q.tags})
        self._many(
            "INSERT INTO quote (digest, text, author_id, last_seen_run) "
            "VALUES (%s, %s, %s, %s) AS new "
            "ON DUPLICATE KEY UPDATE text = new.text, last_seen_run = new.last_seen_run",
            [(q.digest, q.text, authors[q.author], run_id) for q in quotes],
        )
        ids = self._ids("quote", "digest", {q.digest for q in quotes})
        self._many("DELETE FROM quote_tag WHERE quote_id = %s", [(i,) for i in ids.values()])
        links = {(ids[q.digest], tags[t]) for q in quotes for t in q.tags}
        self._many("INSERT INTO quote_tag (quote_id, tag_id) VALUES (%s, %s)", sorted(links))


def statements(script: str) -> list[str]:
    lines = [line for line in script.splitlines() if not line.lstrip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
