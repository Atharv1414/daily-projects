"""Source schema registry and warehouse DDL with versioned migrations.

Readings arrive in two layouts. The registry maps each known header set to a projection
onto the canonical bronze columns, so a renamed or added column is a registry entry, not a
code change scattered across the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

from smart_meter_lakehouse.errors import SchemaError


@dataclass(frozen=True)
class SourceSchema:
    version: int
    columns: frozenset[str]
    projection: str  # SQL select list producing meter_id, read_at, kwh, reading_type
    note: str


READING_SCHEMAS = [
    SourceSchema(
        1,
        frozenset({"meter_id", "read_at", "kwh", "quality_flag"}),
        "meter_id, read_at, kwh, "
        "CASE quality_flag WHEN 'EST' THEN 'E' ELSE 'A' END AS reading_type",
        "original head-end export",
    ),
    SourceSchema(
        2,
        frozenset({"meter_id", "read_at", "consumption_kwh", "reading_type", "quality_flag"}),
        "meter_id, read_at, consumption_kwh AS kwh, reading_type",
        "Oct 2026: kwh renamed to consumption_kwh, reading_type added",
    ),
]


def resolve_reading_schema(columns: list[str]) -> SourceSchema:
    found = frozenset(c.strip().lower() for c in columns)
    for schema in READING_SCHEMAS:
        if schema.columns == found:
            return schema
    # Tolerate additive changes: a known version plus extra unknown columns.
    for schema in sorted(READING_SCHEMAS, key=lambda s: -s.version):
        if schema.columns <= found:
            return schema
    raise SchemaError(f"unrecognised readings header: {sorted(found)}")


MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "schemas and metadata",
        """
        CREATE SCHEMA IF NOT EXISTS meta;
        CREATE SCHEMA IF NOT EXISTS bronze;
        CREATE SCHEMA IF NOT EXISTS silver;
        CREATE SCHEMA IF NOT EXISTS gold;
        CREATE TABLE meta.ingest_log (
            file_name VARCHAR, source VARCHAR, checksum VARCHAR, file_date DATE,
            status VARCHAR, rows BIGINT, schema_version INTEGER, batch_id VARCHAR,
            late_file BOOLEAN, ingested_at TIMESTAMP DEFAULT current_timestamp);
        CREATE TABLE meta.watermarks (source VARCHAR PRIMARY KEY, high_watermark DATE,
            updated_at TIMESTAMP);
        CREATE TABLE meta.batches (batch_id VARCHAR, source VARCHAR, status VARCHAR,
            rows BIGINT, updated_at TIMESTAMP, PRIMARY KEY (batch_id, source));
        CREATE TABLE meta.dag_runs (run_id VARCHAR PRIMARY KEY, through_date DATE,
            status VARCHAR, started_at TIMESTAMP, finished_at TIMESTAMP);
        CREATE TABLE meta.task_runs (run_id VARCHAR, task VARCHAR, status VARCHAR,
            attempts INTEGER, rows_out BIGINT, error VARCHAR, started_at TIMESTAMP,
            finished_at TIMESTAMP);
        CREATE TABLE meta.lineage (run_id VARCHAR, task VARCHAR, input_table VARCHAR,
            output_table VARCHAR);
        CREATE TABLE meta.build_state (name VARCHAR PRIMARY KEY, value TIMESTAMP);
    """,
    ),
    (
        2,
        "bronze layer",
        """
        CREATE TABLE bronze.readings (meter_id VARCHAR, read_at VARCHAR, kwh VARCHAR,
            reading_type VARCHAR, _source_file VARCHAR, _line_no BIGINT, _batch_id VARCHAR,
            _ingested_at TIMESTAMP);
        CREATE TABLE bronze.customer_events (op VARCHAR, event_ts VARCHAR,
            customer_id VARCHAR, meter_id VARCHAR, region VARCHAR, postcode_district VARCHAR,
            tariff_code VARCHAR, psr VARCHAR, _source_file VARCHAR, _line_no BIGINT,
            _batch_id VARCHAR, _ingested_at TIMESTAMP);
        CREATE TABLE bronze.tariffs (tariff_code VARCHAR, display_name VARCHAR,
            unit_rate_p VARCHAR, offpeak_rate_p VARCHAR, offpeak_window VARCHAR,
            standing_charge_p_day VARCHAR, valid_from VARCHAR, valid_to VARCHAR,
            _source_file VARCHAR, _batch_id VARCHAR, _ingested_at TIMESTAMP);
        CREATE TABLE bronze.weather (date VARCHAR, region VARCHAR, mean_temp_c VARCHAR,
            _source_file VARCHAR, _batch_id VARCHAR, _ingested_at TIMESTAMP);
    """,
    ),
    (
        3,
        "silver layer",
        """
        CREATE TABLE silver.readings (meter_id VARCHAR, read_at TIMESTAMP, kwh DOUBLE,
            reading_type VARCHAR, high_usage BOOLEAN, _batch_id VARCHAR, _source_file VARCHAR,
            _updated_at TIMESTAMP, PRIMARY KEY (meter_id, read_at));
        CREATE TABLE silver.quarantine (source VARCHAR, rule VARCHAR, severity VARCHAR,
            record VARCHAR, _source_file VARCHAR, _line_no BIGINT, _batch_id VARCHAR,
            quarantined_at TIMESTAMP DEFAULT current_timestamp);
        CREATE TABLE silver.dq_results (batch_id VARCHAR, source VARCHAR, rule VARCHAR,
            severity VARCHAR, failed BIGINT, checked BIGINT);
        CREATE TABLE silver.customer_events (op VARCHAR, event_ts TIMESTAMP,
            customer_id VARCHAR, meter_id VARCHAR, region VARCHAR, postcode_district VARCHAR,
            tariff_code VARCHAR, psr BOOLEAN, _batch_id VARCHAR, _updated_at TIMESTAMP,
            PRIMARY KEY (customer_id, event_ts, op));
        CREATE TABLE silver.tariffs (tariff_code VARCHAR, display_name VARCHAR,
            unit_rate_p DOUBLE, offpeak_rate_p DOUBLE, standing_charge_p_day DOUBLE,
            valid_from DATE, valid_to DATE, _updated_at TIMESTAMP,
            PRIMARY KEY (tariff_code, valid_from));
        CREATE TABLE silver.weather (date DATE, region VARCHAR, mean_temp_c DOUBLE,
            PRIMARY KEY (date, region));
    """,
    ),
    (
        4,
        "gold star schema",
        """
        CREATE TABLE gold.dim_date (date_key INTEGER PRIMARY KEY, date DATE, day_name VARCHAR,
            is_weekend BOOLEAN, month VARCHAR);
        CREATE TABLE gold.dim_customer (customer_sk UBIGINT, customer_id VARCHAR,
            meter_id VARCHAR, region VARCHAR, postcode_district VARCHAR, tariff_code VARCHAR,
            psr BOOLEAN, valid_from TIMESTAMP, valid_to TIMESTAMP, is_current BOOLEAN);
        CREATE TABLE gold.dim_tariff (tariff_sk UBIGINT, tariff_code VARCHAR,
            display_name VARCHAR, unit_rate_p DOUBLE, offpeak_rate_p DOUBLE,
            standing_charge_p_day DOUBLE, valid_from DATE, valid_to DATE);
        CREATE TABLE gold.fact_halfhour (meter_id VARCHAR, read_at TIMESTAMP,
            date_key INTEGER, period SMALLINT, customer_sk UBIGINT, tariff_sk UBIGINT,
            kwh DOUBLE, rate_p DOUBLE, cost_p DOUBLE, is_offpeak BOOLEAN,
            reading_type VARCHAR);
        CREATE TABLE gold.fact_daily_meter (date DATE, meter_id VARCHAR, customer_sk UBIGINT,
            region VARCHAR, tariff_code VARCHAR, kwh DOUBLE, energy_cost_p DOUBLE,
            standing_charge_p DOUBLE, total_cost_p DOUBLE, reads INTEGER,
            completeness_pct DOUBLE, mean_temp_c DOUBLE);
    """,
    ),
    (
        5,
        "gold serving views",
        """
        CREATE VIEW gold.v_region_daily AS
            SELECT date, region, COUNT(*) AS meters, ROUND(SUM(kwh), 1) AS kwh,
                   ROUND(SUM(total_cost_p) / 100, 2) AS billed_gbp,
                   ROUND(AVG(completeness_pct), 2) AS completeness_pct,
                   ROUND(AVG(mean_temp_c), 1) AS mean_temp_c
            FROM gold.fact_daily_meter GROUP BY date, region;
        CREATE VIEW gold.v_tariff_month AS
            SELECT strftime(f.read_at, '%Y-%m') AS month, t.tariff_code,
                   ROUND(SUM(f.kwh), 1) AS kwh, ROUND(SUM(f.cost_p) / 100, 2) AS energy_gbp,
                   ROUND(100 * AVG(CASE WHEN f.is_offpeak THEN 1 ELSE 0 END), 1)
                       AS offpeak_share_pct
            FROM gold.fact_halfhour f JOIN gold.dim_tariff t USING (tariff_sk)
            GROUP BY 1, 2;
    """,
    ),
]
