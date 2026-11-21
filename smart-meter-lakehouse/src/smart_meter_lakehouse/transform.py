"""Silver layer: type, validate, deduplicate and upsert each source's pending batches."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import duckdb

from smart_meter_lakehouse.errors import DataQualityError
from smart_meter_lakehouse.quality import CUSTOMER_RULES, READING_RULES, evaluate

log = logging.getLogger(__name__)

PARSE_READ_TS = """COALESCE(
    try_strptime(read_at, '%Y-%m-%dT%H:%M:%SZ'),
    (try_strptime(read_at, '%d/%m/%Y %H:%M') AT TIME ZONE 'Europe/London') AT TIME ZONE 'UTC'
)"""


@dataclass
class SilverStats:
    source: str
    batches: list[str]
    checked: int = 0
    rejected: int = 0
    upserted: int = 0

    @property
    def error_rate(self) -> float:
        return self.rejected / self.checked if self.checked else 0.0


def pending_batches(con: duckdb.DuckDBPyConnection, source: str) -> list[str]:
    rows = con.execute(
        "SELECT batch_id FROM meta.batches WHERE source = ? AND status = "
        "'ingested' ORDER BY updated_at",
        [source],
    ).fetchall()
    return [r[0] for r in rows]


def _mark_promoted(con, source: str, batches: list[str]) -> None:
    for b in batches:
        con.execute(
            "UPDATE meta.batches SET status = 'promoted', updated_at = "
            "current_timestamp WHERE batch_id = ? AND source = ?",
            [b, source],
        )


def _batch_filter(batches: list[str]) -> str:
    quoted = ", ".join("'" + b.replace("'", "''") + "'" for b in batches)
    return f"_batch_id IN ({quoted})"


def promote_readings(con: duckdb.DuckDBPyConnection, max_error_rate: float) -> SilverStats:
    batches = pending_batches(con, "readings")
    stats = SilverStats("readings", batches)
    if not batches:
        return stats
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"""CREATE OR REPLACE TEMP VIEW stg_readings AS
            SELECT *, {PARSE_READ_TS} AS read_ts, TRY_CAST(kwh AS DOUBLE) AS kwh_num
            FROM bronze.readings WHERE {_batch_filter(batches)}""")
        outcome = evaluate(con, "stg_readings", READING_RULES, "readings")
        stats.checked, stats.rejected = outcome.checked, outcome.rejected_rows
        if outcome.error_rate > max_error_rate:
            raise DataQualityError(
                f"readings error rate {outcome.error_rate:.2%} exceeds {max_error_rate:.2%}; "
                f"batch not promoted ({outcome.failures})"
            )
        # Latest delivery wins: corrections and late files supersede earlier values.
        con.execute("""CREATE OR REPLACE TEMP TABLE _clean_readings AS
            SELECT meter_id, read_ts AS read_at, kwh_num AS kwh, reading_type,
                   "f_high_usage" AS high_usage, _batch_id, _source_file
            FROM stg_readings_checked WHERE NOT _rejected
            QUALIFY row_number() OVER (PARTITION BY meter_id, read_ts
                                       ORDER BY _ingested_at DESC, _source_file DESC,
                                                _line_no DESC) = 1""")
        stats.upserted = con.execute("SELECT COUNT(*) FROM _clean_readings").fetchone()[0]
        con.execute("""INSERT OR REPLACE INTO silver.readings
                       SELECT *, current_timestamp FROM _clean_readings""")
        _mark_promoted(con, "readings", batches)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return stats


def promote_customers(con: duckdb.DuckDBPyConnection) -> SilverStats:
    batches = pending_batches(con, "customers")
    stats = SilverStats("customers", batches)
    if not batches:
        return stats
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"""CREATE OR REPLACE TEMP VIEW stg_customers AS
            SELECT *, TRY_CAST(replace(event_ts, 'Z', '') AS TIMESTAMP) AS ts,
                   TRY_CAST(psr AS BOOLEAN) AS psr_bool
            FROM bronze.customer_events WHERE {_batch_filter(batches)}""")
        outcome = evaluate(con, "stg_customers", CUSTOMER_RULES, "customers")
        stats.checked, stats.rejected = outcome.checked, outcome.rejected_rows
        before = con.execute("SELECT COUNT(*) FROM silver.customer_events").fetchone()[0]
        # Duplicate deliveries collapse on the (customer_id, event_ts, op) key.
        con.execute("""INSERT OR IGNORE INTO silver.customer_events
            SELECT op, ts, customer_id, meter_id, region, postcode_district, tariff_code,
                   psr_bool, _batch_id, current_timestamp
            FROM stg_customers_checked WHERE NOT _rejected""")
        after = con.execute("SELECT COUNT(*) FROM silver.customer_events").fetchone()[0]
        stats.upserted = after - before
        _mark_promoted(con, "customers", batches)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return stats


def promote_tariffs(con: duckdb.DuckDBPyConnection) -> SilverStats:
    batches = pending_batches(con, "tariffs")
    stats = SilverStats("tariffs", batches)
    if not batches:
        return stats
    rows = con.execute(f"""INSERT OR REPLACE INTO silver.tariffs
        SELECT tariff_code, display_name, CAST(unit_rate_p AS DOUBLE),
               TRY_CAST(offpeak_rate_p AS DOUBLE), CAST(standing_charge_p_day AS DOUBLE),
               CAST(valid_from AS DATE), TRY_CAST(valid_to AS DATE), current_timestamp
        FROM bronze.tariffs WHERE {_batch_filter(batches)}
        QUALIFY row_number() OVER (PARTITION BY tariff_code, valid_from
                                   ORDER BY _ingested_at DESC) = 1""").fetchone()[0]
    stats.checked = stats.upserted = rows
    _mark_promoted(con, "tariffs", batches)
    return stats


def promote_weather(con: duckdb.DuckDBPyConnection) -> SilverStats:
    batches = pending_batches(con, "weather")
    stats = SilverStats("weather", batches)
    if not batches:
        return stats
    rows = con.execute(f"""INSERT OR REPLACE INTO silver.weather
        SELECT CAST(date AS DATE), region, CAST(mean_temp_c AS DOUBLE)
        FROM bronze.weather WHERE {_batch_filter(batches)}
        QUALIFY row_number() OVER (PARTITION BY date, region
                                   ORDER BY _ingested_at DESC) = 1""").fetchone()[0]
    stats.checked = stats.upserted = rows
    _mark_promoted(con, "weather", batches)
    return stats
