import pytest

from last_mile_delivery_bi import cli
from last_mile_delivery_bi.warehouse import build_warehouse
from tests.conftest import SMALL


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "wh.duckdb"
    build_warehouse(path, SMALL).close()
    return path


def test_check_kpis_and_scorecard(db, capsys):
    assert cli.main(["--db", str(db), "check"]) == 0
    assert cli.main(["--db", str(db), "kpis", "--depot", "BHM", "--latest"]) == 0
    assert cli.main(["--db", str(db), "scorecard"]) == 0
    out = capsys.readouterr().out
    assert out.count("[PASS]") == 7
    assert "KPIs for BHM · Nov 2026 MTD" in out and "On-time delivery" in out
    assert "on_time_rank" in out


def test_dashboard_charts_and_docs(db, tmp_path, capsys):
    assert cli.main(["--db", str(db), "dashboard", "--out", str(tmp_path / "site")]) == 0
    assert cli.main(["--db", str(db), "charts", "--out", str(tmp_path / "img")]) == 0
    assert cli.main(["--db", str(db), "docs", "--out", str(tmp_path / "KPI.md")]) == 0
    assert (tmp_path / "site" / "index.html").exists()
    assert len(list((tmp_path / "img").glob("*.png"))) == 4
    assert (tmp_path / "KPI.md").read_text(encoding="utf-8").startswith("# KPI definitions")


def test_build_command_creates_warehouse(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "GeneratorConfig", lambda seed: SMALL)
    db = tmp_path / "new" / "wh.duckdb"
    assert cli.main(["--db", str(db), "build", "--seed", "1"]) == 0
    assert db.exists() and "fact_delivery" in capsys.readouterr().out


def test_missing_database_is_built_on_demand(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "build_warehouse", lambda path: build_warehouse(path, SMALL))
    assert cli.main(["--db", str(tmp_path / "auto.duckdb"), "kpis"]) == 0
    assert "building it first" in capsys.readouterr().out


def test_unknown_command_exits():
    with pytest.raises(SystemExit):
        cli.main(["nope"])
