from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd
import pytest
from conftest import SMALL

from law_firm_profitability_bi import datagen, warehouse
from law_firm_profitability_bi.validation import SQL_CHECKS, run_checks


def one(con, sql, *params):
    return con.execute(sql, list(params)).fetchone()[0]


def test_generation_is_deterministic(sources):
    again = datagen.generate(SMALL)
    for name, frame in sources.items():
        pd.testing.assert_frame_equal(frame, again[name])


def test_every_check_passes(con):
    failed = [c for c in run_checks(con) if not c.ok]
    assert failed == []


def test_rebuild_is_idempotent(sources):
    con = duckdb.connect()
    warehouse.build(con, sources)
    first = one(con, "SELECT sum(closing_wip) FROM fact_matter_month")
    warehouse.build(con, sources)
    assert one(con, "SELECT sum(closing_wip) FROM fact_matter_month") == first


def test_failed_build_leaves_the_old_mart_intact(sources, monkeypatch):
    con = duckdb.connect()
    warehouse.build(con, sources)
    rows = one(con, "SELECT count(*) FROM fact_time")
    real = warehouse.sql_files()
    monkeypatch.setattr(warehouse, "sql_files", lambda: [*real, ("99.sql", "SELECT nope")])
    with pytest.raises(duckdb.Error):
        warehouse.build(con, {**sources, "time": sources["time"].head(10)})
    assert one(con, "SELECT count(*) FROM fact_time") == rows


@pytest.mark.parametrize(
    "reason",
    ["unknown_timekeeper", "unknown_matter", "impossible_hours", "posted_before_worked"],
)
def test_each_fault_is_quarantined(con, reason):
    assert one(con, "SELECT count(*) FROM quarantine_time WHERE reject_reason = ?", reason) > 0
    assert one(con, "SELECT count(*) FROM fact_time WHERE entry_id >= 10000000") == 0


def test_duplicates_are_removed(con):
    assert one(con, "SELECT duplicate_rows FROM load_audit") > 0
    assert one(con, "SELECT count(*) - count(DISTINCT (entry_id, version)) FROM fact_time") == 0


def test_time_uses_the_rate_in_force_when_worked(con):
    wrong = one(
        con,
        """SELECT count(*) FROM fact_time f JOIN dim_timekeeper t USING (timekeeper_key)
        WHERE f.work_date < t.valid_from OR f.work_date >= t.valid_to""",
    )
    assert wrong == 0
    assert one(con, "SELECT count(DISTINCT valid_from) FROM dim_timekeeper") == 3


def test_promotion_changes_grade_without_rewriting_history(con):
    promoted = one(
        con,
        """SELECT count(*) FROM (SELECT timekeeper_id FROM dim_timekeeper
        GROUP BY timekeeper_id HAVING count(DISTINCT grade) > 1)""",
    )
    assert promoted > 0


def test_bridge_handles_a_ragged_hierarchy(con):
    under = dict(
        con.execute(
            "SELECT descendant_id, distance FROM bridge_org WHERE ancestor_id = 'DIS'"
        ).fetchall()
    )
    assert under == {"DIS": 0, "LIT": 1, "ARB": 1, "LIT-COM": 2, "LIT-CON": 2}


def test_financial_year_starts_in_november(con):
    rows = con.execute(
        """SELECT financial_year, financial_period FROM dim_month
        WHERE month_start IN (DATE '2025-10-01', DATE '2025-11-01') ORDER BY month_start"""
    ).fetchall()
    assert rows == [(2025, 12), (2026, 1)]


def test_snapshot_rolls_forward(con):
    broken = one(
        con,
        """WITH s AS (SELECT *, lag(closing_wip, 1, 0) OVER w AS opening FROM fact_matter_month
            WINDOW w AS (PARTITION BY matter_id ORDER BY month_start))
        SELECT count(*) FROM s WHERE opening + recorded - cleared <> closing_wip""",
    )
    assert broken == 0


def test_lifecycle_has_one_row_per_matter(con):
    assert one(con, "SELECT count(*) FROM fact_matter_lifecycle") == SMALL.matters


@pytest.mark.parametrize(
    ("damage", "check"),
    [
        ("UPDATE fact_bill_line SET billed_amount = billed_amount + 1", "billed total"),
        ("DELETE FROM fact_receipt WHERE receipt_id < 50", "cash total"),
        ("INSERT INTO fact_bill_line SELECT * FROM fact_bill_line LIMIT 1", "billed twice"),
        ("DELETE FROM fact_time WHERE entry_id < 20", "every raw row"),
        ("INSERT INTO bridge_org VALUES ('FIRM', 'ARB', 1)", "exactly once"),
        ("UPDATE fact_matter_month SET closing_wip = -1 WHERE matter_id = 'M00001'", "negative"),
    ],
)
def test_checks_detect_damage(sources, damage, check):
    con = duckdb.connect()
    warehouse.build(con, sources)
    con.execute(damage)
    name = next(n for n in SQL_CHECKS if check in n)
    assert con.execute(SQL_CHECKS[name]).fetchone()[0] != 0


def test_missing_database_is_explained(tmp_path):
    with pytest.raises(FileNotFoundError, match="law-bi build"):
        warehouse.open_database(tmp_path / "none.duckdb", read_only=True)


def test_month_dimension_bounds(con):
    assert con.execute("SELECT min(month_start), max(month_end) FROM dim_month").fetchone() == (
        date(2024, 11, 1),
        date(2026, 10, 31),
    )
