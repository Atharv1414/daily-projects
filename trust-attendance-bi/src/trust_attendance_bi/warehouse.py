"""Builds the DuckDB warehouse from the raw MIS exports by running the SQL layers in order."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

import duckdb
import pandas as pd

from .calendar import TERMS, school_days

log = logging.getLogger(__name__)

SQL_LAYERS = ("10_staging", "20_dimensions", "30_facts", "40_aggregates", "50_quality")
RAW_FILES = ("schools.csv", "pupils.csv", "enrolments.csv", "characteristics.csv", "marks.parquet")


class BuildError(RuntimeError):
    """The build stopped: a raw file is missing or a blocking data-quality check failed."""


@dataclass
class BuildReport:
    run_id: str
    seconds: dict[str, float] = field(default_factory=dict)
    rows: dict[str, int] = field(default_factory=dict)
    checks: list[dict] = field(default_factory=list)

    @property
    def failed_blocking(self) -> list[str]:
        return [c["check_name"] for c in self.checks if c["blocking"] and not c["passed"]]


def calendar_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    days = school_days()
    dim_date = pd.DataFrame(
        {
            "date": [d.day for d in days],
            "term": [d.term for d in days],
            "week_start": [d.week_start for d in days],
            "school_week": [d.week_of_year for d in days],
            "month_start": [d.day.replace(day=1) for d in days],
            "weekday": [d.day.strftime("%A") for d in days],
        }
    )
    dim_term = pd.DataFrame(
        {
            "term": [t.name for t in TERMS],
            "term_order": list(range(1, len(TERMS) + 1)),
            "term_start": [t.start for t in TERMS],
            "term_end": [t.end for t in TERMS],
            "census": [t.census for t in TERMS],
        }
    )
    return dim_date, dim_term


def _sql(name: str) -> str:
    return resources.files("trust_attendance_bi").joinpath(f"sql/{name}.sql").read_text()


def build(
    raw_dir: Path, db_path: Path | str = ":memory:"
) -> tuple[duckdb.DuckDBPyConnection, BuildReport]:
    """Runs every layer and returns an open connection plus a report of the run."""
    missing = [f for f in RAW_FILES if not (raw_dir / f).exists()]
    if missing:
        raise BuildError(f"missing raw files in {raw_dir}: {', '.join(missing)}")
    report = BuildReport(run_id=uuid.uuid4().hex[:12])
    con = duckdb.connect(str(db_path))
    started = datetime.now(UTC)

    t0 = time.perf_counter()
    if "'" in raw_dir.as_posix():
        raise BuildError("the raw data path may not contain a quote character")
    con.execute(_sql("00_raw").replace("{raw}", raw_dir.as_posix()))
    dim_date, dim_term = calendar_frames()
    con.register("dim_date_df", dim_date)
    con.register("dim_term_df", dim_term)
    con.execute("CREATE OR REPLACE TABLE dim_date AS SELECT * FROM dim_date_df")
    con.execute("CREATE OR REPLACE TABLE dim_term AS SELECT * FROM dim_term_df")
    report.seconds["load_raw"] = round(time.perf_counter() - t0, 3)

    for layer in SQL_LAYERS:
        t0 = time.perf_counter()
        con.execute(_sql(layer))
        report.seconds[layer] = round(time.perf_counter() - t0, 3)

    for table in (
        "raw_marks",
        "stg_marks",
        "quarantine_marks",
        "dim_pupil",
        "bridge_pupil_term",
        "fact_attendance_session",
        "agg_group_week",
        "agg_group_month",
        "agg_group_term",
        "agg_pupil_term",
    ):
        report.rows[table] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    report.checks = con.execute("SELECT * FROM dq_checks").df().to_dict("records")

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS meta_runs (
            run_id VARCHAR PRIMARY KEY, started TIMESTAMPTZ, finished TIMESTAMPTZ,
            fact_rows BIGINT, quarantined BIGINT, checks_failed INTEGER
        )
        """
    )
    con.execute(
        "INSERT INTO meta_runs VALUES (?, ?, ?, ?, ?, ?)",
        [
            report.run_id,
            started,
            datetime.now(UTC),
            report.rows["fact_attendance_session"],
            report.rows["quarantine_marks"],
            sum(not c["passed"] for c in report.checks),
        ],
    )
    if report.failed_blocking:
        raise BuildError(f"blocking checks failed: {', '.join(report.failed_blocking)}")
    log.info("warehouse built", extra={"run_id": report.run_id, **report.rows})
    return con, report
