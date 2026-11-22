from __future__ import annotations

import pytest

from broadband_support_agent import cli
from broadband_support_agent.config import Settings
from broadband_support_agent.errors import ConfigError
from broadband_support_agent.evals import markdown_report, run_case, run_suite, summarise
from broadband_support_agent.scenarios import CASES, CASES_BY_ID
from broadband_support_agent.tracing import render_html


def test_suite_has_enough_cases_and_all_pass_offline():
    results = run_suite(Settings())
    assert len(results) >= 20
    failed = {r.case_id: r.failures for r in results if not r.passed}
    assert not failed


def test_grader_catches_a_wrong_expectation():
    case = CASES_BY_ID["outage_known"]
    from dataclasses import replace

    wrong = replace(case, expect=replace(case.expect, credited_gbp=5.0))
    result = run_case(wrong, Settings())
    assert not result.passed and any("credited" in f for f in result.failures)


def test_report_rendering():
    results = run_suite(Settings(), only=["outage_known", "hallucinated_credit"])
    summary = summarise(results)
    assert summary["cases"] == 2
    md = markdown_report(
        results,
        {
            "attacks": 1,
            "blocked": 1,
            "block_rate": 1.0,
            "missed": [],
            "benign": 1,
            "false_positives": 0,
            "false_positive_rate": 0.0,
            "hard_attacks": 1,
            "hard_blocked": 0,
        },
        "demo",
        Settings().now,
    )
    assert "Pass rate: 2/2" in md
    html = render_html(
        [
            {
                "name": r.case_id,
                "status": r.status,
                "trace": r.result.trace,
                "spans": r.result.spans,
            }
            for r in results
        ]
    )
    assert html.startswith("<!doctype html>") and "hallucinated_credit" in html


def test_case_ids_unique():
    assert len({c.id for c in CASES}) == len(CASES)


def test_cli_demo_and_eval(tmp_path, capsys):
    trace = tmp_path / "t.html"
    assert (
        cli.main(["run", "--demo", "--scenario", "outage_known", "--trace-html", str(trace)]) == 0
    )
    assert "offline demo mode" in capsys.readouterr().out and trace.exists()
    assert cli.main(["eval", "--demo", "--report-dir", str(tmp_path)]) == 0
    assert (tmp_path / "eval_report.md").exists()


def test_cli_unknown_scenario():
    assert cli.main(["run", "--demo", "--scenario", "nope"]) == 2


def test_live_mode_without_key_fails_cleanly(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("SUPPORT_AGENT_DB", str(tmp_path / "x.db"))
    assert cli.main(["run", "hello"]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_settings_validation(monkeypatch):
    monkeypatch.setenv("SUPPORT_AGENT_MAX_STEPS", "zero")
    with pytest.raises(ConfigError):
        Settings.from_env()
    monkeypatch.setenv("SUPPORT_AGENT_MAX_STEPS", "4")
    monkeypatch.setenv("AGENT_MODEL", "claude-haiku-5-5")
    s = Settings.from_env()
    assert s.max_steps == 4 and s.model == "claude-haiku-5-5"


def test_database_file_is_built_once(tmp_path):
    from broadband_support_agent.database import Repository, connect
    from broadband_support_agent.datagen import ensure_database

    path = ensure_database(tmp_path / "n.db", Settings().now, n_customers=50)
    mtime = path.stat().st_mtime_ns
    ensure_database(path, Settings().now, n_customers=50)
    assert path.stat().st_mtime_ns == mtime
    assert Repository(connect(path)).count("customers") == 57
