from __future__ import annotations

from grocery_retail_bi import cli
from grocery_retail_bi.charts import build_charts
from grocery_retail_bi.dashboard import build_dashboard
from grocery_retail_bi.security import USERS
from grocery_retail_bi.validation import report, run_checks


def test_dashboard_pages_and_kpis(conn, tmp_path):
    res = build_dashboard(conn, USERS["ceo"], tmp_path)
    assert [p.name for p in res.pages] == [
        "overview.html",
        "regions.html",
        "categories.html",
        "trading.html",
    ]
    html = res.pages[0].read_text()
    assert "signed in as" in html and "regions.html" in html and "plotly" in html
    assert res.kpis["net_sales"] > 0


def test_regional_dashboard_only_shows_own_region(conn, tmp_path):
    res = build_dashboard(conn, USERS["rm_north_west"], tmp_path)
    page = (tmp_path / "rm_north_west" / "regions.html").read_text()
    assert "North West" in page and "Scotland" not in page
    ceo = build_dashboard(conn, USERS["ceo"], tmp_path)
    assert res.kpis["net_sales"] < ceo.kpis["net_sales"]


def test_validation_all_pass_and_reconciles_dashboard(conn, tmp_path):
    kpis = build_dashboard(conn, USERS["ceo"], tmp_path).kpis
    checks = run_checks(conn, kpis)
    failed = [c for c in checks if not c.passed and c.severity == "error"]
    assert not failed, failed
    assert any("dashboard" in c.name for c in checks)
    assert "checks passed" in report(checks)


def test_validation_detects_tampering(conn, tmp_path):
    kpis = build_dashboard(conn, USERS["ceo"], tmp_path).kpis
    kpis["net_sales"] += 1.0  # a dashboard number that no longer ties to source
    bad = [c for c in run_checks(conn, kpis) if not c.passed]
    assert [c.name for c in bad] == ["dashboard L12M net sales = source"]


def test_charts_written(conn, tmp_path):
    paths = build_charts(conn, tmp_path)
    assert len(paths) == 6 and all(p.stat().st_size > 5_000 for p in paths)


def test_cli_catalog_and_errors(capsys):
    assert cli.main(["catalog"]) == 0
    assert "net_sales" in capsys.readouterr().out
