import json

import pytest

from expense_tracker.cli import run
from expense_tracker.config import Settings
from expense_tracker.errors import ValidationError

from .conftest import TODAY


def cli(tracker, *argv):
    return run(list(argv), tracker=tracker, today=TODAY)


def test_add_with_auto_category_and_budget_warning(tracker, capsys):
    assert cli(tracker, "budget", "food", "20", "--month", "2026-11") == 0
    assert (
        cli(tracker, "add", "25", "-m", "CARD PAYMENT TO TESCO STORES 2231*99", "-d", "2026-11-03")
        == 0
    )
    out = capsys.readouterr().out
    assert "on food (auto: builtin) at Tesco Stores" in out
    assert "over by £5.00" in out


def test_add_warns_when_projected_to_overspend(tracker, capsys):
    cli(tracker, "budget", "transport", "100", "--month", "2026-11")
    cli(tracker, "add", "60", "transport", "-d", "2026-11-02")
    assert "on track to spend £120.00" in capsys.readouterr().out


def test_errors_return_specific_exit_codes(tracker, capsys):
    assert cli(tracker, "add", "5", "spaceships") == 2
    assert cli(tracker, "add", "5") == 2
    assert cli(tracker, "delete", "999") == 3
    assert cli(tracker, "import", "/nonexistent.csv") == 4
    assert "Unknown category" in capsys.readouterr().err


def test_end_to_end_import_summary_report_export(tracker, tmp_path, capsys):
    assert run(["generate-data", str(tmp_path)]) == 0
    assert cli(tracker, "import", str(tmp_path / "bank_a_statement.csv")) == 0
    assert cli(tracker, "import", str(tmp_path / "bank_b_statement.csv")) == 0
    for argv in (
        ["summary", "--month", "2026-10"],
        ["trend", "--months", "6", "--month", "2026-10"],
        ["anomalies"],
        ["list", "--month", "2026-10", "--sort", "amount", "--page-size", "5"],
        ["imports"],
        ["db-info"],
    ):
        assert cli(tracker, *argv) == 0
    out = capsys.readouterr().out
    assert "duplicates skipped" in out and "Summary for 2026-10" in out
    assert "Currys Pc World" in out  # planted £899 spike is detected
    report = tmp_path / "report.html"
    assert cli(tracker, "report", str(report), "--month", "2026-10") == 0
    assert "<svg" in report.read_text() and "Top merchants" in report.read_text()
    export = tmp_path / "oct.json"
    assert cli(tracker, "export", str(export), "--month", "2026-10") == 0
    records = json.loads(export.read_text())
    assert records and {"date", "merchant", "amount", "category"} <= records[0].keys()


def test_recurring_and_rules_commands(tracker, capsys):
    assert cli(tracker, "recurring", "add", "Rent", "1450", "housing", "--start", "2026-09-01") == 0
    assert cli(tracker, "recurring", "run") == 0
    assert cli(tracker, "recurring", "run") == 0
    assert cli(tracker, "recurring", "list") == 0
    assert cli(tracker, "rule", "(?i)corner shop", "food") == 0
    assert cli(tracker, "add", "3.20", "-m", "Corner Shop") == 0
    out = capsys.readouterr().out
    assert "Created 3 recurring" in out and "Created 0 recurring" in out
    assert "(auto: rule:(?i)corner shop)" in out


def test_budget_rollover(tracker, capsys):
    cli(tracker, "budget", "food", "300", "--month", "2026-10")
    assert cli(tracker, "budget-rollover") == 0
    assert "Copied 1 budget(s) into 2026-11" in capsys.readouterr().out


def test_settings_from_env(tmp_path):
    s = Settings.from_env(
        {"EXPENSE_DB": str(tmp_path / "x.db"), "EXPENSE_LOG_LEVEL": "info", "EXPENSE_LOG_JSON": "1"}
    )
    assert (s.db_path.name, s.log_level, s.log_json) == ("x.db", "INFO", True)
    with pytest.raises(ValidationError):
        Settings.from_env({"EXPENSE_ANOMALY_THRESHOLD": "-1"})


def test_real_database_file_via_env(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("EXPENSE_DB", str(tmp_path / "real.db"))
    assert run(["add", "4.50", "food", "-d", "2026-11-01"]) == 0
    assert run(["db-info"]) == 0
    assert "Expenses: 1" in capsys.readouterr().out


def test_json_logging_includes_extra_fields():
    import logging

    from expense_tracker.logging_setup import JsonFormatter

    record = logging.makeLogRecord(
        {"name": "expense_tracker.importer", "levelname": "INFO", "msg": "done", "inserted": 7}
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["msg"] == "done" and payload["inserted"] == 7


def test_bench_command_runs_small(capsys):
    assert run(["bench", "--rows", "2000"]) == 0
    out = capsys.readouterr().out
    assert "Import throughput" in out and "reimport_noop" in out
