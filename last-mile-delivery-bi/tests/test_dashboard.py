from datetime import date

from last_mile_delivery_bi.charts import build_charts
from last_mile_delivery_bi.dashboard import build_dashboard, latest_period, scorecard_table, trend_figure


def test_latest_period_is_month_to_date(con):
    p = latest_period(con)
    assert (p.start, p.end) == (date(2026, 11, 1), date(2026, 11, 14))
    assert p.label == "Nov 2026 MTD" and p.prev_label == "Oct 2026"
    assert p.prev_start == date(2026, 10, 1) and p.prev_end == date(2026, 10, 31)


def test_trend_figure_has_a_depot_filter(con):
    depots = ["BHM", "BRS", "GLA", "LDN", "LDS", "MAN"]
    fig = trend_figure(con, depots)
    assert len(fig.data) == 2 * (len(depots) + 1)
    buttons = fig.layout.updatemenus[0].buttons
    assert [b.label for b in buttons] == ["Network", *depots]
    assert sum(buttons[3].args[0]["visible"]) == 2


def test_scorecard_links_to_drill_down_pages(con):
    table = scorecard_table(con, latest_period(con))
    assert table.count('href="depot-') == 6
    assert "Network" in table and "--rag:" in table


def test_dashboard_site_is_complete_and_offline(con, tmp_path):
    pages = build_dashboard(con, tmp_path)
    assert [p.name for p in pages] == ["index.html"] + [
        f"depot-{c}.html" for c in ["BHM", "BRS", "GLA", "LDN", "LDS", "MAN"]
    ]
    assert (tmp_path / "plotly.min.js").stat().st_size > 1_000_000
    index = pages[0].read_text(encoding="utf-8")
    assert "Depot scorecard" in index and "updatemenus" in index
    assert 'src="http' not in index  # no CDN dependency
    bhm = (tmp_path / "depot-BHM.html").read_text(encoding="utf-8")
    assert "BHM-R01" in bhm and "index.html" in bhm


def test_png_charts_are_written(con, tmp_path):
    paths = build_charts(con, tmp_path)
    assert len(paths) == 4
    for p in paths:
        assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and p.stat().st_size > 10_000
