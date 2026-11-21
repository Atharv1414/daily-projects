import pytest

from hotel_revenue_agent.cli import main
from hotel_revenue_agent.evals import ALL_CASES, extract_numbers, numbers_match, run_suite


def test_suite_size():
    assert len(ALL_CASES) >= 30
    assert len({c.id for c in ALL_CASES}) == len(ALL_CASES)


def test_reference_trajectories_pass_on_fresh_data(settings):
    report = run_suite(settings, "reference")
    failures = [
        (r.case.id, [c for c in r.checks if not c.passed]) for r in report.results if not r.passed
    ]
    assert failures == []


def test_naive_variant_is_caught_by_graders(settings):
    report = run_suite(settings, "naive")
    failed = {r.case.id for r in report.results if not r.passed}
    assert {"room_revenue_2025", "group_occupancy_2025"} <= failed
    assert report.failure_reasons()["answer_correct"] == len(failed)


@pytest.mark.parametrize(
    "answer,expected,ok",
    [
        ("Revenue was £31,024,103.64.", 31024103.64, True),
        ("Occupancy was 73.2%.", 73.1657, True),
        ("Occupancy was 0.7317.", 73.1657, True),
        ("Occupancy was 69%.", 73.1657, False),
        ("No number here", 12, False),
    ],
)
def test_numbers_match(answer, expected, ok):
    assert numbers_match(answer, expected) is ok


def test_extract_numbers():
    assert extract_numbers("£1,200.50 and -3 and 7%") == [1200.5, -3.0, 7.0]


def test_cli_demo_and_eval(monkeypatch, settings, capsys):
    monkeypatch.setenv("HOTEL_DB", str(settings.db_path))
    monkeypatch.setenv("AGENT_TRACES_DIR", str(settings.traces_dir))
    monkeypatch.setenv("AGENT_REPORTS_DIR", str(settings.reports_dir))
    assert main(["ask", "--demo", "--scenario", "injection_in_data"]) == 0
    out = capsys.readouterr().out
    assert "[blocked] DROP TABLE bookings" in out
    assert main(["eval"]) == 0
    assert "100.0%" in capsys.readouterr().out
    assert main(["ask", "--demo", "--scenario", "nope"]) == 1


def test_cli_live_without_key_fails_cleanly(monkeypatch, settings, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("HOTEL_DB", str(settings.db_path))
    assert main(["ask", "How many hotels?"]) == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
