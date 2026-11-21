from dataclasses import replace
from datetime import date

import pytest

from smart_meter_lakehouse.cli import main
from smart_meter_lakehouse.pipeline import run_pipeline
from smart_meter_lakehouse.report import write_report
from smart_meter_lakehouse.warehouse import connect
from tests.conftest import q

END = date(2026, 10, 4)

TOTALS = """SELECT COUNT(*), ROUND(SUM(kwh), 3), ROUND(SUM(cost_p), 2)
            FROM gold.fact_halfhour"""


def test_incremental_equals_full_load(cfg, tmp_path):
    full = connect(tmp_path / "full.duckdb")
    assert run_pipeline(full, cfg, END)[0].ok
    inc = connect(tmp_path / "inc.duckdb")
    for through in (date(2026, 9, 18), date(2026, 9, 25), END):
        assert run_pipeline(inc, cfg, through)[0].ok
    assert q(full, TOTALS) == q(inc, TOTALS)
    assert q(full, "SELECT ROUND(SUM(total_cost_p), 2) FROM gold.fact_daily_meter") == q(
        inc, "SELECT ROUND(SUM(total_cost_p), 2) FROM gold.fact_daily_meter"
    )


def test_rerun_is_idempotent(con, cfg):
    run_pipeline(con, cfg, END)
    before = q(con, TOTALS)
    result, ctx = run_pipeline(con, cfg, END)
    assert result.ok and ctx["gold"].affected_dates == 0
    assert q(con, TOTALS) == before
    assert q(con, "SELECT COUNT(*) FROM silver.readings")[0][0] == before[0][0]


def test_every_fact_row_resolves_dimensions(con, cfg):
    run_pipeline(con, cfg, END)
    assert (
        q(
            con,
            "SELECT COUNT(*) FROM gold.fact_halfhour WHERE customer_sk IS NULL "
            "OR tariff_sk IS NULL",
        )[0][0]
        == 0
    )
    assert q(con, "SELECT ROUND(SUM(kwh), 3) FROM silver.readings") == q(
        con, "SELECT ROUND(SUM(kwh), 3) FROM gold.fact_daily_meter"
    )


def test_late_reads_complete_earlier_days(con, cfg):
    run_pipeline(con, cfg, date(2026, 9, 20))
    partial = q(con, "SELECT SUM(reads) FROM gold.fact_daily_meter WHERE date = '2026-09-20'")
    run_pipeline(con, cfg, date(2026, 9, 21))
    complete = q(con, "SELECT SUM(reads) FROM gold.fact_daily_meter WHERE date = '2026-09-20'")
    assert complete[0][0] > partial[0][0]


def test_latest_correction_wins(con, cfg):
    run_pipeline(con, cfg, END)
    rows = q(
        con,
        """
        SELECT s.kwh, b.kwh, b._source_file FROM silver.readings s
        JOIN bronze.readings b ON b.meter_id = s.meter_id
         AND b._source_file > 'readings_' || CAST(CAST(s.read_at AS DATE) AS VARCHAR) || '.csv'
         AND b.read_at = strftime(s.read_at, '%Y-%m-%dT%H:%M:%SZ')
        LIMIT 50""",
    )
    assert rows, "expected some late/corrected reads"
    assert all(abs(s - float(b)) < 1e-9 for s, b, _ in rows if b is not None)


def test_scd2_and_tariff_as_of_pricing(con, cfg):
    run_pipeline(con, cfg, END)
    # Price cap change: FLEX-STD unit rate is 24.86p in September and 26.10p from 1 October.
    rates = q(
        con,
        """SELECT CAST(read_at AS DATE) >= DATE '2026-10-01', MIN(rate_p),
                             MAX(rate_p)
                      FROM gold.fact_halfhour f JOIN gold.dim_tariff t USING (tariff_sk)
                      WHERE t.tariff_code = 'FLEX-STD' GROUP BY 1 ORDER BY 1""",
    )
    assert rates == [(False, 24.86, 24.86), (True, 26.1, 26.1)]
    # Off-peak: EV-NIGHT local 01:00 (00:00 UTC in BST) is off-peak at 7.5p.
    offpeak = q(
        con,
        """SELECT DISTINCT f.rate_p FROM gold.fact_halfhour f
                        JOIN gold.dim_tariff t USING (tariff_sk)
                        WHERE t.tariff_code = 'EV-NIGHT' AND f.is_offpeak
                          AND CAST(f.read_at AS DATE) < DATE '2026-10-01'""",
    )
    assert offpeak == [(7.5,)]
    versions = q(con, "SELECT COUNT(*) FROM gold.dim_customer WHERE NOT is_current")[0][0]
    current = q(con, "SELECT COUNT(*) FROM gold.dim_customer WHERE is_current")[0][0]
    assert current <= 40 + versions and current >= 39


def test_dq_threshold_blocks_promotion_then_recovers(con, cfg):
    strict = replace(cfg, max_error_rate=0.0001)
    result, _ = run_pipeline(con, strict, date(2026, 9, 17))
    assert result.tasks["silver_readings"].status == "failed"
    assert result.tasks["facts"].status == "skipped"
    assert q(con, "SELECT COUNT(*) FROM silver.readings")[0][0] == 0
    assert q(con, "SELECT DISTINCT status FROM meta.batches WHERE source = 'readings'") == [
        ("ingested",)
    ]
    result, _ = run_pipeline(con, cfg, date(2026, 9, 17))
    assert result.ok and q(con, "SELECT COUNT(*) FROM silver.readings")[0][0] > 0


@pytest.mark.parametrize("failures,ok", [(2, True), (10, False)])
def test_flaky_tariff_api(con, cfg, failures, ok):
    result, _ = run_pipeline(
        con, replace(cfg, flaky_tariff_failures=failures), date(2026, 9, 17), sleep=lambda s: None
    )
    assert result.ok is ok
    assert result.tasks["ingest_tariffs"].attempts == min(failures + 1, cfg.max_retries + 1)


def test_report_and_charts(con, cfg):
    run_pipeline(con, cfg, END)
    path = write_report(con, cfg.reports_dir)
    text = path.read_text()
    assert "kwh_negative" in text and "late-arriving reads" in text
    assert (cfg.reports_dir / "consumption_by_region.png").stat().st_size > 10_000


def test_cli_end_to_end(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("METERLAKE_LANDING", str(tmp_path / "landing"))
    monkeypatch.setenv("METERLAKE_DB", str(tmp_path / "w.duckdb"))
    monkeypatch.setenv("METERLAKE_REPORTS", str(tmp_path / "rep"))
    assert main(["generate", "--meters", "10", "--days", "3"]) == 0
    assert main(["run", "--through", "2026-09-17"]) == 0
    assert "SUCCESS" in capsys.readouterr().out
    assert main(["status"]) == 0 and main(["dag"]) == 0
    assert "flowchart LR" in capsys.readouterr().out
