"""Gold layer: SCD Type 2 dimensions and incrementally rebuilt fact tables.

Incremental strategy: the gold build keeps a high-water timestamp in ``meta.build_state``.
Dates whose silver readings changed since then are rebuilt, plus every date on or after the
earliest dimension change (a late CDC event or a new tariff period can re-price history).
Rebuilding a date is DELETE + INSERT inside one transaction, so reruns are idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import duckdb

GOLD_MARK = "gold_facts"
EPOCH = datetime(1900, 1, 1)


@dataclass
class GoldStats:
    affected_dates: int
    halfhour_rows: int
    daily_rows: int


def build_dim_date(con: duckdb.DuckDBPyConnection) -> int:
    con.execute("DELETE FROM gold.dim_date")
    con.execute("""INSERT INTO gold.dim_date
        SELECT CAST(strftime(d, '%Y%m%d') AS INTEGER), CAST(d AS DATE), dayname(d),
               isodow(d) >= 6, strftime(d, '%Y-%m')
        FROM (SELECT range AS d FROM range(
                (SELECT COALESCE(MIN(CAST(read_at AS DATE)), DATE '2026-01-01')
                 FROM silver.readings),
                (SELECT COALESCE(MAX(CAST(read_at AS DATE)), DATE '2026-01-01')
                 FROM silver.readings) + INTERVAL 1 DAY, INTERVAL 1 DAY))""")
    return con.execute("SELECT COUNT(*) FROM gold.dim_date").fetchone()[0]


def build_dim_customer(con: duckdb.DuckDBPyConnection) -> int:
    """SCD2 rebuilt from the full CDC history, so out-of-order events land correctly.

    Surrogate keys are hashes of (customer_id, version start) so they stay stable across
    rebuilds. The first version for each meter is back-dated to 1900 because the initial
    CRM snapshot describes customers who existed before the feed started.
    """
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("DELETE FROM gold.dim_customer")
        con.execute("""INSERT INTO gold.dim_customer
            WITH ordered AS (
                SELECT *, LEAD(event_ts) OVER (PARTITION BY customer_id
                                               ORDER BY event_ts, op) AS next_ts
                FROM silver.customer_events
            ), versions AS (
                SELECT * FROM ordered WHERE op IN ('c', 'u')
            )
            SELECT hash(customer_id, event_ts), customer_id, meter_id, region,
                   postcode_district, tariff_code, psr,
                   CASE WHEN row_number() OVER (PARTITION BY meter_id ORDER BY event_ts) = 1
                        THEN TIMESTAMP '1900-01-01' ELSE event_ts END,
                   COALESCE(next_ts, TIMESTAMP '9999-12-31'),
                   next_ts IS NULL
            FROM versions""")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return con.execute("SELECT COUNT(*) FROM gold.dim_customer").fetchone()[0]


def build_dim_tariff(con: duckdb.DuckDBPyConnection) -> int:
    con.execute("DELETE FROM gold.dim_tariff")
    con.execute("""INSERT INTO gold.dim_tariff
        SELECT hash(tariff_code, valid_from), tariff_code, display_name, unit_rate_p,
               offpeak_rate_p, standing_charge_p_day, valid_from,
               COALESCE(valid_to, LEAD(valid_from) OVER w - 1, DATE '9999-12-31')
        FROM silver.tariffs
        WINDOW w AS (PARTITION BY tariff_code ORDER BY valid_from)""")
    return con.execute("SELECT COUNT(*) FROM gold.dim_tariff").fetchone()[0]


def _mark(con: duckdb.DuckDBPyConnection) -> datetime:
    row = con.execute("SELECT value FROM meta.build_state WHERE name = ?", [GOLD_MARK]).fetchone()
    return row[0] if row else EPOCH


def affected_dates(con: duckdb.DuckDBPyConnection, since: datetime) -> list[date]:
    rows = con.execute(
        """
        WITH dim_change AS (
            SELECT MIN(d) AS d FROM (
                SELECT CAST(event_ts AS DATE) AS d FROM silver.customer_events
                WHERE _updated_at > ? AND ? > TIMESTAMP '1900-01-01'
                UNION ALL
                SELECT valid_from FROM silver.tariffs
                WHERE _updated_at > ? AND ? > TIMESTAMP '1900-01-01'))
        SELECT DISTINCT CAST(read_at AS DATE) AS d FROM silver.readings
        WHERE _updated_at > ?
           OR CAST(read_at AS DATE) >= (SELECT d FROM dim_change)
        ORDER BY d""",
        [since, since, since, since, since],
    ).fetchall()
    return [r[0] for r in rows]


def build_facts(con: duckdb.DuckDBPyConnection, full_refresh: bool = False) -> GoldStats:
    since = EPOCH if full_refresh else _mark(con)
    started = con.execute("SELECT current_timestamp::TIMESTAMP").fetchone()[0]
    dates = affected_dates(con, since)
    if not dates:
        return GoldStats(0, 0, 0)
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("CREATE OR REPLACE TEMP TABLE _affected (d DATE PRIMARY KEY)")
        con.executemany("INSERT INTO _affected VALUES (?)", [[d] for d in dates])
        con.execute(
            "DELETE FROM gold.fact_halfhour WHERE CAST(read_at AS DATE) IN "
            "(SELECT d FROM _affected)"
        )
        con.execute("""INSERT INTO gold.fact_halfhour
            WITH r AS (
                SELECT * FROM silver.readings
                WHERE CAST(read_at AS DATE) IN (SELECT d FROM _affected)
            ), rc AS (
                SELECT r.*, c.customer_sk, c.tariff_code
                FROM r ASOF LEFT JOIN gold.dim_customer c
                  ON r.meter_id = c.meter_id AND r.read_at >= c.valid_from
            ), rct AS (
                SELECT rc.*, t.tariff_sk, t.unit_rate_p, t.offpeak_rate_p,
                       CAST((rc.read_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/London'
                            AS TIME) AS local_time
                FROM rc ASOF LEFT JOIN gold.dim_tariff t
                  ON rc.tariff_code = t.tariff_code
                 AND CAST(rc.read_at AS DATE) >= t.valid_from
            )
            SELECT meter_id, read_at, CAST(strftime(read_at, '%Y%m%d') AS INTEGER),
                   hour(read_at) * 2 + minute(read_at) // 30 + 1, customer_sk, tariff_sk, kwh,
                   CASE WHEN is_offpeak THEN offpeak_rate_p ELSE unit_rate_p END,
                   kwh * CASE WHEN is_offpeak THEN offpeak_rate_p ELSE unit_rate_p END,
                   is_offpeak, reading_type
            FROM (SELECT *, offpeak_rate_p IS NOT NULL
                            AND local_time >= TIME '00:30' AND local_time < TIME '05:30'
                            AS is_offpeak FROM rct)""")
        con.execute("DELETE FROM gold.fact_daily_meter WHERE date IN (SELECT d FROM _affected)")
        con.execute("""INSERT INTO gold.fact_daily_meter
            WITH daily AS (
                SELECT CAST(f.read_at AS DATE) AS date, f.meter_id,
                       arg_max(f.customer_sk, f.read_at) AS customer_sk,
                       arg_max(f.tariff_sk, f.read_at) AS tariff_sk,
                       SUM(f.kwh) AS kwh, SUM(f.cost_p) AS energy_cost_p, COUNT(*) AS reads
                FROM gold.fact_halfhour f
                WHERE CAST(f.read_at AS DATE) IN (SELECT d FROM _affected)
                GROUP BY 1, 2
            )
            SELECT d.date, d.meter_id, d.customer_sk, c.region, c.tariff_code,
                   ROUND(d.kwh, 3), ROUND(d.energy_cost_p, 2), t.standing_charge_p_day,
                   ROUND(d.energy_cost_p + COALESCE(t.standing_charge_p_day, 0), 2), d.reads,
                   ROUND(100.0 * d.reads / 48, 2), w.mean_temp_c
            FROM daily d
            LEFT JOIN gold.dim_customer c USING (customer_sk)
            LEFT JOIN gold.dim_tariff t USING (tariff_sk)
            LEFT JOIN silver.weather w ON w.date = d.date AND w.region = c.region""")
        con.execute("INSERT OR REPLACE INTO meta.build_state VALUES (?, ?)", [GOLD_MARK, started])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    hh = con.execute(
        "SELECT COUNT(*) FROM gold.fact_halfhour WHERE CAST(read_at AS DATE) IN "
        "(SELECT d FROM _affected)"
    ).fetchone()[0]
    daily = con.execute(
        "SELECT COUNT(*) FROM gold.fact_daily_meter WHERE date IN (SELECT d FROM _affected)"
    ).fetchone()[0]
    return GoldStats(len(dates), hh, daily)
