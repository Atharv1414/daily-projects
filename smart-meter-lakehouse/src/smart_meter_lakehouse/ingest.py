"""Bronze ingestion: discover landing files, skip ones already loaded, land raw rows.

Idempotency comes from the content checksum in ``meta.ingest_log``: a re-sent file with the
same bytes is logged as a duplicate and never loaded twice, while a corrected file (new
bytes) is loaded and the silver layer resolves which version of each row wins. The
per-source watermark records the newest file date seen, so files older than it are
flagged as late deliveries.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import duckdb
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from smart_meter_lakehouse.errors import SchemaError, TransientSourceError
from smart_meter_lakehouse.schema import resolve_reading_schema

log = logging.getLogger(__name__)

FILE_PATTERN = re.compile(
    r"^(?P<source>readings|customers|tariffs|weather)_(?P<date>\d{4}-\d{2}(?:-\d{2})?)"
    r"(?P<suffix>_[a-z0-9]+)?\.(?P<ext>csv|jsonl|json|parquet)$"
)


@dataclass(frozen=True)
class LandingFile:
    path: Path
    source: str
    file_date: date

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


@dataclass
class IngestStats:
    source: str
    loaded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    rows: int = 0


class TariffRecord(BaseModel):
    """Contract for the tariff API. Unknown fields are ignored; missing ones fail."""

    model_config = ConfigDict(extra="ignore")
    tariff_code: str = Field(min_length=2)
    display_name: str
    unit_rate_p: float = Field(gt=0, lt=200)
    offpeak_rate_p: float | None = Field(default=None, gt=0, lt=200)
    offpeak_window: str | None = None
    standing_charge_p_day: float = Field(ge=0, lt=500)
    valid_from: date
    valid_to: date | None = None


class TariffPayload(BaseModel):
    data: list[TariffRecord]
    meta: dict


def discover(landing: Path, source: str, through: date) -> list[LandingFile]:
    files = []
    for path in sorted(landing.iterdir()) if landing.exists() else []:
        m = FILE_PATTERN.match(path.name)
        if not m or m.group("source") != source:
            continue
        raw = m.group("date")
        file_date = date.fromisoformat(raw if len(raw) == 10 else f"{raw}-01")
        if file_date <= through:
            files.append(LandingFile(path, source, file_date))
    return files


def _already_loaded(con: duckdb.DuckDBPyConnection, checksum: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM meta.ingest_log WHERE checksum = ? AND status = 'loaded'", [checksum]
    ).fetchone()
    return row is not None


def _watermark(con: duckdb.DuckDBPyConnection, source: str) -> date | None:
    row = con.execute(
        "SELECT high_watermark FROM meta.watermarks WHERE source = ?", [source]
    ).fetchone()
    return row[0] if row else None


def _log(
    con,
    f: LandingFile,
    checksum: str,
    status: str,
    rows: int,
    batch_id: str,
    schema_version: int | None,
    late: bool,
) -> None:
    con.execute(
        "INSERT INTO meta.ingest_log (file_name, source, checksum, file_date, status, "
        "rows, schema_version, batch_id, late_file) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            f.path.name,
            f.source,
            checksum,
            f.file_date,
            status,
            rows,
            schema_version,
            batch_id,
            late,
        ],
    )


def _load_readings(con, f: LandingFile, batch_id: str) -> tuple[int, int]:
    rel = con.read_csv(str(f.path), all_varchar=True, header=True)
    schema = resolve_reading_schema(rel.columns)
    con.register("_landing", rel)
    try:
        con.execute(
            f"""
            INSERT INTO bronze.readings
            SELECT {schema.projection}, ? AS _source_file,
                   row_number() OVER () AS _line_no, ? AS _batch_id, current_timestamp
            FROM _landing""",
            [f.path.name, batch_id],
        )
    finally:
        con.unregister("_landing")
    return _rows_for(con, "bronze.readings", f, batch_id), schema.version


def _load_customers(con, f: LandingFile, batch_id: str) -> tuple[int, int]:
    rows = []
    for line_no, line in enumerate(f.path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            event = {"op": None, "event_ts": None, "customer": {}}
        c = event.get("customer") or {}
        psr = c.get("psr")
        rows.append(
            (
                event.get("op"),
                event.get("event_ts"),
                c.get("customer_id"),
                c.get("meter_id"),
                c.get("region"),
                c.get("postcode_district"),
                c.get("tariff_code"),
                None if psr is None else str(psr).lower(),
                f.path.name,
                line_no,
                batch_id,
            )
        )
    if rows:
        con.executemany(
            "INSERT INTO bronze.customer_events VALUES (?,?,?,?,?,?,?,?,?,?,?, current_timestamp)",
            rows,
        )
    return len(rows), 1


def _load_tariffs(con, f: LandingFile, batch_id: str) -> tuple[int, int]:
    payload = TariffPayload.model_validate_json(f.path.read_text())
    rows = [
        (
            r.tariff_code,
            r.display_name,
            str(r.unit_rate_p),
            None if r.offpeak_rate_p is None else str(r.offpeak_rate_p),
            r.offpeak_window,
            str(r.standing_charge_p_day),
            r.valid_from.isoformat(),
            None if r.valid_to is None else r.valid_to.isoformat(),
            f.path.name,
            batch_id,
        )
        for r in payload.data
    ]
    con.executemany(
        "INSERT INTO bronze.tariffs VALUES (?,?,?,?,?,?,?,?,?,?, current_timestamp)", rows
    )
    return len(rows), 1


def _load_weather(con, f: LandingFile, batch_id: str) -> tuple[int, int]:
    con.execute(
        """INSERT INTO bronze.weather
                   SELECT CAST(date AS VARCHAR), region, CAST(mean_temp_c AS VARCHAR), ?, ?,
                          current_timestamp FROM read_parquet(?)""",
        [f.path.name, batch_id, str(f.path)],
    )
    return _rows_for(con, "bronze.weather", f, batch_id), 1


def _rows_for(con, table: str, f: LandingFile, batch_id: str) -> int:
    return con.execute(
        f"SELECT COUNT(*) FROM {table} WHERE _source_file = ? AND _batch_id = ?",
        [f.path.name, batch_id],
    ).fetchone()[0]


LOADERS: dict[str, Callable] = {
    "readings": _load_readings,
    "customers": _load_customers,
    "tariffs": _load_tariffs,
    "weather": _load_weather,
}


def ingest_source(
    con: duckdb.DuckDBPyConnection,
    landing: Path,
    source: str,
    through: date,
    batch_id: str,
    before_load: Callable[[], None] | None = None,
) -> IngestStats:
    """Land every new file for ``source`` dated on or before ``through``.

    Each file loads in its own transaction with its log entry, so a crash part-way through
    leaves either the whole file or none of it.
    """
    stats = IngestStats(source)
    files = discover(landing, source, through)
    if files and before_load:
        before_load()  # e.g. a flaky API check; may raise TransientSourceError
    mark = _watermark(con, source)
    for f in files:
        checksum = f.checksum
        if _already_loaded(con, checksum):
            stats.skipped.append(f.path.name)
            continue
        late = mark is not None and f.file_date < mark
        con.execute("BEGIN TRANSACTION")
        try:
            rows, version = LOADERS[source](con, f, batch_id)
            _log(con, f, checksum, "loaded", rows, batch_id, version, late)
            con.execute("COMMIT")
        except (SchemaError, ValidationError, duckdb.Error) as exc:
            con.execute("ROLLBACK")
            log.warning("rejected %s: %s", f.path.name, exc)
            _log(con, f, checksum, "rejected", 0, batch_id, None, late)
            stats.rejected.append(f.path.name)
            continue
        except TransientSourceError:
            con.execute("ROLLBACK")
            raise
        stats.loaded.append(f.path.name)
        stats.rows += rows
    if stats.loaded:
        newest = max(f.file_date for f in files if f.path.name in stats.loaded)
        con.execute(
            """INSERT INTO meta.watermarks VALUES (?, ?, current_timestamp)
                       ON CONFLICT (source) DO UPDATE SET
                       high_watermark = greatest(meta.watermarks.high_watermark,
                                                 excluded.high_watermark),
                       updated_at = excluded.updated_at""",
            [source, newest],
        )
        con.execute(
            "INSERT OR REPLACE INTO meta.batches VALUES (?, ?, 'ingested', ?, current_timestamp)",
            [batch_id, source, stats.rows],
        )
    return stats
