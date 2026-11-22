"""SQLite persistence for the fictional ISP "Northwire Broadband".

The schema is versioned with ``PRAGMA user_version`` so an old database file is rebuilt rather
than silently misread. Writes that must not race (booking an engineer slot) use a conditional
UPDATE inside a transaction, so two agents cannot book the same slot.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE exchanges (
    exchange_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    region TEXT NOT NULL
);
CREATE TABLE plans (
    plan_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    technology TEXT NOT NULL CHECK (technology IN ('FTTC', 'FTTP')),
    download_mbps INTEGER NOT NULL,
    min_guaranteed_mbps INTEGER NOT NULL,
    monthly_price_gbp REAL NOT NULL
);
CREATE TABLE customers (
    account_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    postcode TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    exchange_id TEXT NOT NULL REFERENCES exchanges(exchange_id),
    plan_id TEXT NOT NULL REFERENCES plans(plan_id),
    start_date TEXT NOT NULL,
    contract_end TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'suspended', 'ceased')),
    vulnerable INTEGER NOT NULL DEFAULT 0,
    vulnerability_note TEXT
);
CREATE TABLE line_profiles (
    account_id TEXT PRIMARY KEY REFERENCES customers(account_id),
    sync_down_mbps REAL NOT NULL,
    noise_margin_db REAL NOT NULL,
    fault_code TEXT
);
CREATE TABLE invoices (
    invoice_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES customers(account_id),
    period TEXT NOT NULL,
    description TEXT NOT NULL,
    amount_gbp REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('paid', 'due', 'overdue')),
    issued_on TEXT NOT NULL
);
CREATE INDEX ix_invoices_account ON invoices(account_id, period);
CREATE TABLE outages (
    outage_id TEXT PRIMARY KEY,
    exchange_id TEXT NOT NULL REFERENCES exchanges(exchange_id),
    started_at TEXT NOT NULL,
    est_restore_at TEXT,
    resolved_at TEXT,
    description TEXT NOT NULL
);
CREATE TABLE credits (
    credit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL REFERENCES customers(account_id),
    amount_gbp REAL NOT NULL CHECK (amount_gbp > 0),
    reason TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    approved_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE tickets (
    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT REFERENCES customers(account_id),
    category TEXT NOT NULL,
    priority TEXT NOT NULL CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);
CREATE TABLE engineer_slots (
    slot_id TEXT PRIMARY KEY,
    region TEXT NOT NULL,
    slot_date TEXT NOT NULL,
    time_window TEXT NOT NULL CHECK (time_window IN ('AM', 'PM')),
    booked_account TEXT REFERENCES customers(account_id),
    version INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE help_articles (
    article_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    tags TEXT NOT NULL
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None)  # autocommit; explicit BEGIN below
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(r) for r in cursor.fetchall()]


class Repository:
    """All SQL lives here; tools and policy never build queries themselves."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # --- reads ------------------------------------------------------------------------
    def customer(self, account_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """SELECT c.*, p.name AS plan_name, p.technology, p.download_mbps,
                      p.min_guaranteed_mbps, p.monthly_price_gbp, e.name AS exchange_name,
                      e.region
               FROM customers c JOIN plans p USING (plan_id) JOIN exchanges e USING (exchange_id)
               WHERE c.account_id = ?""",
            (account_id,),
        ).fetchone()
        return dict(row) if row else None

    def line_profile(self, account_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM line_profiles WHERE account_id = ?", (account_id,)
        ).fetchone()
        return dict(row) if row else None

    def active_outages(self, exchange_id: str, now: datetime) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                """SELECT * FROM outages
                   WHERE exchange_id = ? AND started_at <= ?
                     AND (resolved_at IS NULL OR resolved_at > ?)
                   ORDER BY started_at""",
                (exchange_id, now.isoformat(), now.isoformat()),
            )
        )

    def invoices(self, account_id: str, months: int) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                """SELECT * FROM invoices WHERE account_id = ?
                     AND period IN (SELECT DISTINCT period FROM invoices WHERE account_id = ?
                                    ORDER BY period DESC LIMIT ?)
                   ORDER BY period DESC, invoice_id""",
                (account_id, account_id, months),
            )
        )

    def invoice(self, invoice_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)
        ).fetchone()
        return dict(row) if row else None

    def credits_since(self, account_id: str, since: datetime) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM credits WHERE account_id = ? AND created_at >= ? "
                "ORDER BY created_at",
                (account_id, since.isoformat()),
            )
        )

    def credit_by_key(self, key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM credits WHERE idempotency_key = ?", (key,)
        ).fetchone()
        return dict(row) if row else None

    def free_slots(self, region: str, after: datetime, limit: int = 6) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                """SELECT slot_id, slot_date, time_window, version FROM engineer_slots
                   WHERE region = ? AND booked_account IS NULL AND slot_date > ?
                   ORDER BY slot_date, time_window LIMIT ?""",
                (region, after.date().isoformat(), limit),
            )
        )

    def slot(self, slot_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM engineer_slots WHERE slot_id = ?", (slot_id,)
        ).fetchone()
        return dict(row) if row else None

    def search_articles(self, terms: list[str], limit: int = 3) -> list[dict[str, Any]]:
        articles = _rows(self.conn.execute("SELECT * FROM help_articles"))
        scored = []
        for art in articles:
            haystack = f"{art['title']} {art['tags']} {art['body']}".lower()
            score = sum(haystack.count(t) for t in terms) + 3 * sum(
                t in art["title"].lower() for t in terms
            )
            if score:
                scored.append((score, art))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["article_id"]))
        return [a for _, a in scored[:limit]]

    def tickets(self, account_id: str) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                "SELECT * FROM tickets WHERE account_id = ? ORDER BY ticket_id", (account_id,)
            )
        )

    # --- writes -----------------------------------------------------------------------
    def insert_credit(
        self, account_id: str, amount: float, reason: str, key: str, approved_by: str, now: datetime
    ) -> dict[str, Any]:
        with transaction(self.conn):
            self.conn.execute(
                """INSERT INTO credits (account_id, amount_gbp, reason, idempotency_key,
                                        approved_by, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
                (account_id, round(amount, 2), reason, key, approved_by, now.isoformat()),
            )
        found = self.credit_by_key(key)
        assert found is not None
        return found

    def book_slot(self, slot_id: str, account_id: str, expected_version: int) -> bool:
        """Optimistic lock: succeeds only if the slot is still free at the version we read."""
        with transaction(self.conn):
            cur = self.conn.execute(
                """UPDATE engineer_slots SET booked_account = ?, version = version + 1
                   WHERE slot_id = ? AND booked_account IS NULL AND version = ?""",
                (account_id, slot_id, expected_version),
            )
        return cur.rowcount == 1

    def insert_ticket(
        self,
        account_id: str | None,
        category: str,
        priority: str,
        summary: str,
        now: datetime,
    ) -> int:
        with transaction(self.conn):
            cur = self.conn.execute(
                """INSERT INTO tickets (account_id, category, priority, summary, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (account_id, category, priority, summary, now.isoformat()),
            )
        return int(cur.lastrowid or 0)

    def count(self, table: str) -> int:
        if not table.isidentifier():
            raise ValueError(f"bad table name {table!r}")
        return int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
