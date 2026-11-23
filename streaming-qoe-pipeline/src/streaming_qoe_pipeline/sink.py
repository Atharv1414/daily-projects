"""DuckDB sink. Outputs, consumer offsets and operator state commit in **one transaction**.

That transaction is what makes the pipeline exactly-once *in effect*. After a crash, the
processor resumes from offsets that match the restored state exactly, so every output is
produced once. The keyed upserts (``INSERT OR REPLACE``) are a second guard if a commit is ever
replayed.
"""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

from .errors import CheckpointError

SCHEMA_VERSION = 1

_QOE_COLUMNS = """
    attempts BIGINT, plays BIGINT, startup_ms_sum BIGINT, watch_ms BIGINT, rebuffer_ms BIGINT,
    rebuffer_events BIGINT, bitrate_ms_sum BIGINT, errors BIGINT, fatal_errors BIGINT,
    events BIGINT, rebuffer_ratio DOUBLE, avg_bitrate_kbps DOUBLE, avg_startup_ms DOUBLE
"""

DDL = [
    "CREATE TABLE IF NOT EXISTS schema_migrations "
    "(version INTEGER PRIMARY KEY, applied_at TIMESTAMP)",
    f"""CREATE TABLE IF NOT EXISTS qoe_minute (
        window_start BIGINT, window_end BIGINT, cdn VARCHAR, region VARCHAR, device VARCHAR,
        {_QOE_COLUMNS}, active_sessions BIGINT,
        PRIMARY KEY (window_start, cdn, region, device))""",
    f"""CREATE TABLE IF NOT EXISTS qoe_cdn_region_5m (
        window_start BIGINT, window_end BIGINT, cdn VARCHAR, region VARCHAR, {_QOE_COLUMNS},
        PRIMARY KEY (window_start, cdn, region))""",
    """CREATE TABLE IF NOT EXISTS sessions (
        session_id VARCHAR PRIMARY KEY, viewer_id VARCHAR, device VARCHAR, cdn VARCHAR,
        isp VARCHAR, region VARCHAR, content_id VARCHAR, start_ms BIGINT, end_ms BIGINT,
        attempted BOOLEAN, started BOOLEAN, exit_before_start BOOLEAN, startup_ms BIGINT,
        watch_ms BIGINT, rebuffer_ms BIGINT, rebuffer_count BIGINT, rebuffer_ratio DOUBLE,
        avg_bitrate_kbps DOUBLE, bitrate_switches BIGINT, end_reason VARCHAR, events BIGINT)""",
    """CREATE TABLE IF NOT EXISTS late_events (
        event_id VARCHAR, operator VARCHAR, event_type VARCHAR, event_ms BIGINT,
        watermark_ms BIGINT, lateness_ms BIGINT, windows_dropped INTEGER,
        PRIMARY KEY (event_id, operator))""",
    """CREATE TABLE IF NOT EXISTS dead_letters (
        partition INTEGER, "offset" BIGINT, reason VARCHAR, detail VARCHAR, raw VARCHAR,
        PRIMARY KEY (partition, "offset"))""",
    """CREATE TABLE IF NOT EXISTS alerts (
        window_start BIGINT, window_end BIGINT, cdn VARCHAR, region VARCHAR,
        rebuffer_ratio DOUBLE, baseline_ratio DOUBLE, z_score DOUBLE, watch_ms BIGINT,
        severity VARCHAR, PRIMARY KEY (window_start, cdn, region))""",
    """CREATE TABLE IF NOT EXISTS consumer_offsets (
        group_id VARCHAR, partition INTEGER, next_offset BIGINT,
        PRIMARY KEY (group_id, partition))""",
    """CREATE TABLE IF NOT EXISTS operator_state (
        group_id VARCHAR PRIMARY KEY, checkpoint_id BIGINT, watermark_ms BIGINT,
        state BLOB, state_bytes BIGINT, committed_at TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS pipeline_runs (
        run_id VARCHAR PRIMARY KEY, group_id VARCHAR, started_at TIMESTAMP,
        finished_at TIMESTAMP, status VARCHAR, stats JSON)""",
]

# Output table -> (conflict policy, primary key).
_OUTPUTS: dict[str, tuple[str, list[str]]] = {
    "qoe_minute": ("REPLACE", ["window_start", "cdn", "region", "device"]),
    "qoe_cdn_region_5m": ("REPLACE", ["window_start", "cdn", "region"]),
    "sessions": ("REPLACE", ["session_id"]),
    "late_events": ("IGNORE", ["event_id", "operator"]),
    "dead_letters": ("IGNORE", ["partition", "offset"]),
    "alerts": ("REPLACE", ["window_start", "cdn", "region"]),
}


@dataclass
class Checkpoint:
    checkpoint_id: int
    watermark_ms: int
    offsets: dict[int, int]
    state: dict[str, object]


@dataclass
class OutputBuffer:
    """Rows produced since the last checkpoint, keyed by destination table."""

    rows: dict[str, list[dict[str, object]]] = field(
        default_factory=lambda: {name: [] for name in _OUTPUTS}
    )

    def add(self, table: str, rows: list[dict[str, object]]) -> None:
        self.rows[table].extend(rows)

    def count(self, table: str) -> int:
        return len(self.rows[table])

    def clear(self) -> None:
        for rows in self.rows.values():
            rows.clear()


class DuckDBSink:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(self.path)
        self._migrate()
        self._columns = {
            table: [r[0] for r in self.con.execute(f"DESCRIBE {table}").fetchall()]
            for table in _OUTPUTS
        }

    def _migrate(self) -> None:
        for statement in DDL:
            self.con.execute(statement)
        applied = self.con.execute("SELECT max(version) FROM schema_migrations").fetchone()
        if applied is None or applied[0] is None:
            self.con.execute("INSERT INTO schema_migrations VALUES (?, now())", [SCHEMA_VERSION])

    def close(self) -> None:
        self.con.close()

    def load_checkpoint(self, group_id: str) -> Checkpoint | None:
        row = self.con.execute(
            "SELECT checkpoint_id, watermark_ms, state FROM operator_state WHERE group_id = ?",
            [group_id],
        ).fetchone()
        offsets = dict(
            self.con.execute(
                "SELECT partition, next_offset FROM consumer_offsets WHERE group_id = ?",
                [group_id],
            ).fetchall()
        )
        if row is None:
            if offsets:
                raise CheckpointError("offsets exist without operator state")
            return None
        try:
            state = json.loads(zlib.decompress(row[2]))
        except (zlib.error, json.JSONDecodeError) as exc:
            raise CheckpointError("operator state blob is corrupt") from exc
        return Checkpoint(
            int(row[0]), int(row[1]), {int(k): int(v) for k, v in offsets.items()}, state
        )

    def commit(
        self,
        group_id: str,
        checkpoint_id: int,
        watermark_ms: int,
        offsets: dict[int, int],
        state: dict[str, object],
        outputs: OutputBuffer,
    ) -> int:
        """Atomically write outputs, offsets and state. Returns the compressed state size."""
        blob = zlib.compress(json.dumps(state, separators=(",", ":")).encode(), level=1)
        self.con.execute("BEGIN TRANSACTION")
        try:
            for table, rows in outputs.rows.items():
                if rows:
                    self._write(table, rows)
            self.con.executemany(
                "INSERT OR REPLACE INTO consumer_offsets VALUES (?, ?, ?)",
                [[group_id, p, o] for p, o in sorted(offsets.items())],
            )
            self.con.execute(
                "INSERT OR REPLACE INTO operator_state VALUES (?, ?, ?, ?, ?, now())",
                [group_id, checkpoint_id, watermark_ms, blob, len(blob)],
            )
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise
        return len(blob)

    def _write(self, table: str, rows: list[dict[str, object]]) -> None:
        policy, key = _OUTPUTS[table]
        frame = pd.DataFrame(rows).reindex(columns=self._columns[table])
        # DuckDB rejects two rows for one key in a single upsert, so keep the last one
        # (e.g. a session id that re-opened within one checkpoint interval).
        frame = frame.drop_duplicates(subset=key, keep="last" if policy == "REPLACE" else "first")
        self.con.register("incoming", frame)
        try:
            cols = ", ".join(f'"{c}"' for c in self._columns[table])
            self.con.execute(
                f"INSERT OR {policy} INTO {table} ({cols}) SELECT {cols} FROM incoming"
            )
        finally:
            self.con.unregister("incoming")

    def record_run(
        self, run_id: str, group_id: str, started: float, status: str, stats: dict
    ) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO pipeline_runs VALUES (?, ?, to_timestamp(?), now(), ?, ?)",
            [run_id, group_id, started, status, json.dumps(stats, default=str)],
        )

    def query(self, sql: str, params: list[object] | None = None) -> pd.DataFrame:
        return self.con.execute(sql, params or []).df()

    def table_snapshot(self, table: str) -> list[tuple]:
        """Every row of a table in a canonical order (used to compare runs)."""
        cols = ", ".join(f'"{c}"' for c in self._columns.get(table, ["*"]))
        return self.con.execute(f"SELECT {cols} FROM {table} ORDER BY ALL").fetchall()
