"""Read-only access to the hotel warehouse with an authorizer, timeout and row limits."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hotel_revenue_agent.errors import SQLGuardError, ToolError
from hotel_revenue_agent.sql_guard import check_sql, guard

ALLOWED_TABLES = frozenset(
    {"hotels", "room_types", "guests", "bookings", "ancillary_charges", "reviews"}
)
MAX_CELL_CHARS = 200
DENIED_FUNCTIONS = frozenset({"load_extension", "readfile", "writefile", "edit"})

TABLE_DESCRIPTIONS = {
    "hotels": "One row per hotel in the group (12 UK hotels).",
    "room_types": "Room categories per hotel with room_count and base_rate_gbp.",
    "guests": "Guest profiles. special_requests is free text typed by guests (untrusted).",
    "bookings": "One row per reservation. status is completed, cancelled or no_show. "
    "Room revenue = nightly_rate_gbp * nights for completed stays.",
    "ancillary_charges": "Extra spend during completed stays (F&B, Spa, Parking...).",
    "reviews": "Post-stay review score 1-10 (nullable) and a short comment.",
}


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    elapsed_ms: float
    sql: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_payload(self) -> dict[str, Any]:
        """JSON-serialisable result. Long text cells are clipped to keep context small."""

        def clip(v: Any) -> Any:
            if isinstance(v, str) and len(v) > MAX_CELL_CHARS:
                return v[:MAX_CELL_CHARS] + "..."
            if isinstance(v, float):
                return round(v, 4)
            return v

        return {
            "columns": self.columns,
            "rows": [[clip(v) for v in r] for r in self.rows],
            "row_count": self.row_count,
            "truncated": self.truncated,
            "elapsed_ms": round(self.elapsed_ms, 2),
        }


def make_authorizer(schema_objects: frozenset[str]):
    """Build a SQLite authorizer that only allows reads of allowlisted tables.

    A READ of a name that is not a schema object is a CTE defined inside the query (SQLite
    reports recursive CTE reads as table reads), so it is allowed. Real objects outside the
    allowlist, SQLite internals and table-valued pragma functions are denied.
    """

    def authorizer(
        action: int, arg1: str | None, arg2: str | None, _db: str | None, _trigger: str | None
    ) -> int:
        if action == sqlite3.SQLITE_READ:
            name = (arg1 or "").lower()
            if name in ALLOWED_TABLES:
                return sqlite3.SQLITE_OK
            if name in schema_objects or name.startswith(("sqlite_", "pragma_")):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION:
            fn = (arg2 or "").lower()
            return sqlite3.SQLITE_DENY if fn in DENIED_FUNCTIONS else sqlite3.SQLITE_OK
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    return authorizer


class Warehouse:
    """Thin read-only gateway. Every query goes through ``sql_guard`` and the authorizer."""

    def __init__(self, db_path: Path, max_rows: int = 200, timeout_ms: int = 3_000) -> None:
        if not Path(db_path).exists():
            raise ToolError(f"Database not found at {db_path}", hint="Run `hotel-agent init-db`.")
        self.db_path = Path(db_path)
        self.max_rows = max_rows
        self.timeout_ms = timeout_ms
        self._con = sqlite3.connect(
            f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False
        )
        self._schema_cache: dict[str, list[dict[str, Any]]] = {}
        objects = self._con.execute("SELECT lower(name) FROM sqlite_master").fetchall()
        self._authorizer = make_authorizer(frozenset(r[0] for r in objects))

    def close(self) -> None:
        self._con.close()

    def _columns(self, table: str) -> list[dict[str, Any]]:
        if table not in self._schema_cache:
            cur = self._con.execute(f"PRAGMA table_info({table})")  # table is allowlisted
            self._schema_cache[table] = [
                {"name": r[1], "type": r[2], "nullable": not r[3], "pk": bool(r[5])}
                for r in cur.fetchall()
            ]
        return self._schema_cache[table]

    def list_tables(self) -> list[dict[str, Any]]:
        out = []
        for table in sorted(ALLOWED_TABLES):
            (count,) = self._con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            out.append({"table": table, "rows": count, "description": TABLE_DESCRIPTIONS[table]})
        return out

    def describe_table(self, table: str) -> dict[str, Any]:
        table = self._require_table(table)
        return {
            "table": table,
            "description": TABLE_DESCRIPTIONS[table],
            "columns": self._columns(table),
        }

    def sample_rows(self, table: str, n: int) -> QueryResult:
        table = self._require_table(table)
        return self.query(f"SELECT * FROM {table} ORDER BY RANDOM() LIMIT {int(n)}")

    def _require_table(self, table: str) -> str:
        name = table.strip().lower()
        if name not in ALLOWED_TABLES:
            raise ToolError(
                f"Unknown table {table!r}.",
                hint=f"Available tables: {', '.join(sorted(ALLOWED_TABLES))}.",
            )
        return name

    def explain(self, sql: str) -> list[str]:
        """Compile the query without running it; returns the query plan lines."""
        cleaned = check_sql(sql)
        try:
            self._con.set_authorizer(self._authorizer)
            plan = self._con.execute(f"EXPLAIN QUERY PLAN {cleaned}").fetchall()
        except sqlite3.DatabaseError as exc:
            raise self._translate(exc) from exc
        finally:
            self._con.set_authorizer(None)
        return [str(row[-1]) for row in plan]

    def query(self, sql: str) -> QueryResult:
        guarded = guard(sql, self.max_rows)
        deadline = time.perf_counter() + self.timeout_ms / 1000

        def progress() -> int:
            return 1 if time.perf_counter() > deadline else 0

        start = time.perf_counter()
        self._con.set_authorizer(self._authorizer)
        self._con.set_progress_handler(progress, 10_000)
        try:
            cur = self._con.execute(guarded.sql)
            rows = [list(r) for r in cur.fetchall()]
            columns = [d[0] for d in cur.description or []]
        except sqlite3.DatabaseError as exc:
            raise self._translate(exc) from exc
        finally:
            self._con.set_authorizer(None)
            self._con.set_progress_handler(None, 0)
        elapsed = (time.perf_counter() - start) * 1000
        truncated = len(rows) > guarded.limit
        return QueryResult(columns, rows[: guarded.limit], truncated, elapsed, sql=sql.strip())

    def _translate(self, exc: sqlite3.DatabaseError) -> ToolError:
        msg = str(exc)
        if "interrupted" in msg:
            return ToolError(
                f"Query exceeded the {self.timeout_ms} ms time limit.",
                hint="Aggregate earlier, add filters, or avoid cross joins.",
            )
        if "not authorized" in msg or "prohibited" in msg:
            return SQLGuardError(
                "Query touches an object outside the allowlist.",
                hint=f"Allowed tables: {', '.join(sorted(ALLOWED_TABLES))}.",
            )
        if "no such column" in msg or "no such table" in msg:
            return ToolError(msg, hint="Call describe_table to check the exact column names.")
        return ToolError(f"SQL error: {msg}", hint="Fix the syntax and try again.")
