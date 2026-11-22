from __future__ import annotations

from fnol_business_case import cli, report


def test_end_to_end_results(results):
    assert results.metrics.npv > 0 and 0 < results.break_even_adoption < 0.55
    assert results.assumptions["cycle_days_saved"].base > 0


def test_business_case_document(results, tmp_path):
    paths = report.write_all(results, tmp_path)
    md = (tmp_path / "BUSINESS_CASE.md").read_text()
    for section in (
        "Executive summary",
        "Pilot evaluation",
        "```mermaid",
        "RACI",
        "Financial case",
        "Risks",
        "Recommendation",
    ):
        assert section in md
    assert "nan" not in md.lower().replace("financ", "")
    assert len(list((tmp_path / "charts").glob("*.png"))) == 9
    assert (tmp_path / "BACKLOG.md").exists() and len(paths) > 15


def test_formatters():
    assert report.gbp(2_076_795) == "£2.08m" and report.gbp(623) == "£623"
    assert report.gbp(-492_408) == "-£492,408"
    assert report.pct(float("nan")) == "n/a" and report.years(float("inf")) == "never"


def test_cli_what_if_and_errors(capsys):
    assert cli.main(["what-if", "target_adoption=0.3"]) == 0
    assert "NPV" in capsys.readouterr().out
    assert cli.main(["what-if", "bogus=1"]) == 2
