import json
import re

from mortgage_exits import cli, report
from mortgage_exits.config import Economics


def test_report_is_complete(results, study, tmp_path):
    path = report.write(results, study, Economics(), tmp_path)
    text = path.read_text()
    images = re.findall(r"\((figures/.+?)\)", text)
    assert len(images) == 8 and all((tmp_path / i).stat().st_size > 10_000 for i in images)
    assert "nan" not in text.lower().replace("finance", "")
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["left"] < summary["left_naive"]
    assert f"{summary['left']:.0%} remortgage elsewhere" in text


def test_cli_round_trips_through_csv(tmp_path, capsys):
    data, out = tmp_path / "data", tmp_path / "out"
    small = ["--accounts", "9000", "--data", str(data)]
    assert cli.main(["generate", *small]) == 0
    assert cli.main(["run", *small, "--out", str(out)]) == 0
    assert "Brier score" in capsys.readouterr().out
    assert (out / "FINDINGS.md").exists()


def test_csv_and_memory_give_the_same_study(raw, study, tmp_path):
    from mortgage_exits.cleaning import build_study

    cli.generate(study, tmp_path)
    a, _, _ = build_study(raw, study)
    b, _, _ = build_study(cli.load(tmp_path), study)
    assert a[["account_id", "exit", "cause"]].equals(b[["account_id", "exit", "cause"]])


def test_cli_explains_missing_data(tmp_path, caplog):
    assert cli.main(["run", "--data", str(tmp_path)]) == 1
    assert "Run `generate` first" in caplog.text


def test_cli_refuses_a_tiny_study(caplog):
    assert cli.main(["run", "--accounts", "5"]) == 1
    assert "at least 200" in caplog.text


def test_environment_sets_the_size(monkeypatch):
    from mortgage_exits.config import Study

    monkeypatch.setenv("MORTGAGE_ACCOUNTS", "777")
    assert Study.from_env().accounts == 777
