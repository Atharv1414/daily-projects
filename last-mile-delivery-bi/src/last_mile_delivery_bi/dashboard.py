"""Interactive operations dashboard, written as a small offline static site.

``index.html`` is the network view: KPI tiles with RAG status, a weekly trend with a
depot filter, a depot scorecard that links to one drill-down page per depot, and
root-cause charts. Plotly's JavaScript is written once beside the pages so the site
works offline and can be opened straight from disk or hosted on any file server.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from .metrics import KPIS, compute_kpis, format_value, rag_status
from .warehouse import query_df

# Validated categorical palette (fixed order) and reserved status colours.
SERIES = ["#257de0", "#f47230", "#00b894", "#f2a600", "#ee7fac", "#008a17"]
STATUS = {"green": "#0aac23", "amber": "#fbb315", "red": "#dc3c3d", "none": "#9c9c9c"}
STATUS_LABEL = {
    "green": "✔ On target",
    "amber": "▲ Near target",
    "red": "✖ Off target",
    "none": "Volume measure",
}
TILE_KPIS = [
    "parcels",
    "first_attempt_rate",
    "on_time_rate",
    "return_rate",
    "cost_per_parcel",
    "parcels_per_hour",
    "vehicle_utilisation",
    "co2_kg_per_parcel",
]
SCORECARD_KPIS = TILE_KPIS[1:]

CSS = """
:root { --surface:#ffffff; --page:#f6f7f9; --text:#191919; --muted:#666666; --line:#e3e5e8; }
* { box-sizing:border-box; }
body { margin:0; background:var(--page); color:var(--text);
       font:14px/1.45 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
header { background:#14213d; color:#fff; padding:18px 28px; }
header h1 { margin:0; font-size:20px; } header p { margin:4px 0 0; color:#c9d1e0; }
header a { color:#c9d1e0; }
main { max-width:1280px; margin:0 auto; padding:20px 16px 40px; }
.tiles { display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:12px; }
.tile { background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:12px 14px;
        border-top:4px solid var(--rag); }
.tile .label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.03em; }
.tile .value { font-size:26px; font-weight:650; margin:2px 0; font-variant-numeric:tabular-nums; }
.tile .meta { color:var(--muted); font-size:12px; }
.card { background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:14px 16px;
        margin-top:16px; }
.card h2 { font-size:15px; margin:0 0 6px; }
.card p.note { color:var(--muted); margin:0 0 8px; font-size:12px; }
.grid2 { display:grid; grid-template-columns:repeat(auto-fit, minmax(420px, 1fr)); gap:0 16px; }
table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
th, td { padding:7px 8px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
th:first-child, td:first-child { text-align:left; }
th { color:var(--muted); font-weight:600; font-size:12px; }
td.rag { border-left:4px solid var(--rag); }
.wrap { overflow-x:auto; }
.grid2 > * { min-width:0; }
@media (max-width:520px) { .grid2 { grid-template-columns:1fr; } }
"""


@dataclass(frozen=True)
class Period:
    """The reporting period shown on the tiles: the latest month, compared with the one before."""

    start: date
    end: date
    label: str
    prev_start: date
    prev_end: date
    prev_label: str


def latest_period(con: duckdb.DuckDBPyConnection) -> Period:
    """Latest month in the data (month to date if partial) and the previous full month."""
    last = con.execute("SELECT MAX(full_date) FROM v_kpi_depot_day").fetchone()[0]
    start = last.replace(day=1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end.replace(day=1)
    month_end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    suffix = " MTD" if last < month_end else ""
    return Period(start, last, f"{start:%b %Y}{suffix}", prev_start, prev_end, f"{prev_start:%b %Y}")


def _tiles(con: duckdb.DuckDBPyConnection, period: Period, depot: str | None = None) -> str:
    now = compute_kpis(con, depot, period.start, period.end)
    prev = compute_kpis(con, depot, period.prev_start, period.prev_end)
    out = []
    for key in TILE_KPIS:
        kpi = KPIS[key]
        value, before = now[key], prev[key]
        status = rag_status(kpi, value)
        target = "" if kpi.target is None else f"Target {format_value(kpi, kpi.target)} · "
        if key == "parcels":
            delta = f"{period.prev_label}: {format_value(kpi, before)}"
        elif value is not None and before is not None:
            diff = value - before
            arrow = "▲" if diff > 0 else "▼" if diff < 0 else "■"
            shown = f"{abs(diff) * 100:.1f} pts" if kpi.unit == "pct" else format_value(kpi, abs(diff))
            delta = f"{arrow} {shown} vs {period.prev_label}"
        else:
            delta = ""
        out.append(
            f'<div class="tile" style="--rag:{STATUS[status]}">'
            f'<div class="label">{html.escape(kpi.label)}</div>'
            f'<div class="value">{format_value(kpi, value)}</div>'
            f'<div class="meta">{target}{STATUS_LABEL[status]}</div>'
            f'<div class="meta">{delta}</div></div>'
        )
    return '<div class="tiles">' + "".join(out) + "</div>"


def _layout(fig: go.Figure, height: int = 360) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(family="-apple-system, Segoe UI, Roboto, Arial", size=12, color="#191919"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hoverlabel=dict(bgcolor="#ffffff"),
    )
    fig.update_xaxes(showgrid=False, linecolor="#c8ccd2")
    fig.update_yaxes(gridcolor="#eceef1", zeroline=False)
    return fig


def _div(fig: go.Figure) -> str:
    return fig.to_html(
        full_html=False, include_plotlyjs=False, config={"displaylogo": False, "responsive": True}
    )


def trend_figure(con: duckdb.DuckDBPyConnection, depots: list[str]) -> go.Figure:
    """Weekly on-time and first-attempt rates with a dropdown to filter by depot."""
    trend = query_df(con, "SELECT * FROM v_weekly_trend ORDER BY week_start")
    options = ["ALL", *depots]
    fig = go.Figure()
    for i, code in enumerate(options):
        df = trend[trend["depot_code"] == code]
        for j, (col, name) in enumerate(
            [("on_time_rate", "On-time"), ("first_attempt_rate", "First-attempt")]
        ):
            fig.add_trace(
                go.Scatter(
                    x=df["week_start"],
                    y=df[col],
                    name=name,
                    mode="lines+markers",
                    line=dict(width=2, color=SERIES[j]),
                    marker=dict(size=8, line=dict(width=2, color="#ffffff")),
                    visible=i == 0,
                    hovertemplate="w/c %{x|%d %b}: %{y:.1%}<extra>" + name + "</extra>",
                )
            )
    for key, dash in [("on_time_rate", "dash"), ("first_attempt_rate", "dot")]:
        fig.add_hline(
            y=KPIS[key].target,
            line=dict(color="#9c9c9c", width=1, dash=dash),
            annotation_text=f"{KPIS[key].label} target",
            annotation_position="bottom right",
            annotation_font_color="#666666",
        )
    buttons = []
    for i, code in enumerate(options):
        visible = [False] * (2 * len(options))
        visible[2 * i] = visible[2 * i + 1] = True
        buttons.append(
            dict(label="Network" if code == "ALL" else code, method="update", args=[{"visible": visible}])
        )
    fig.update_layout(
        updatemenus=[dict(buttons=buttons, direction="down", x=1, xanchor="right", y=1.18, yanchor="top")]
    )
    fig.update_yaxes(tickformat=".0%")
    return _layout(fig)


def pareto_figure(con: duckdb.DuckDBPyConnection, depot: str = "ALL") -> go.Figure:
    df = query_df(
        con, "SELECT * FROM v_failure_pareto WHERE depot_code = ? ORDER BY reason_rank DESC", [depot]
    )
    fig = go.Figure(
        go.Bar(
            x=df["failures"],
            y=df["failure_reason"],
            orientation="h",
            marker=dict(color=SERIES[0], line=dict(width=2, color="#ffffff")),
            text=[f"{s:.0%}" for s in df["share"]],
            textposition="outside",
            customdata=df[["share", "cumulative_share"]],
            hovertemplate="%{y}: %{x:,} failures (%{customdata[0]:.1%}, cumulative %{customdata[1]:.0%})"
            "<extra></extra>",
        )
    )
    fig.update_xaxes(title="First-attempt failures", range=[0, float(df["failures"].max()) * 1.15])
    return _layout(fig, 300)


def utilisation_figure(con: duckdb.DuckDBPyConnection) -> go.Figure:
    df = query_df(con, "SELECT * FROM v_utilisation_bands ORDER BY utilisation_band")
    labels = df["utilisation_band"].str.slice(3)
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=df["on_time_rate"],
            marker=dict(color=SERIES[0], line=dict(width=2, color="#ffffff")),
            text=[f"{v:.1%}" for v in df["on_time_rate"]],
            textposition="outside",
            customdata=df[["route_days", "out_of_time_rate"]],
            hovertemplate="Van %{x} full: on-time %{y:.1%}<br>%{customdata[0]:,} route days, "
            "%{customdata[1]:.1%} 'out of time' failures<extra></extra>",
        )
    )
    fig.update_yaxes(tickformat=".0%", range=[0, 1])
    fig.update_xaxes(title="Van utilisation on the day")
    return _layout(fig, 300)


def fleet_figure(con: duckdb.DuckDBPyConnection) -> go.Figure:
    df = query_df(con, "SELECT * FROM v_fleet_mix ORDER BY depot_code, fuel_type")
    fig = go.Figure()
    for i, fuel in enumerate(["Diesel", "Electric"]):
        d = df[df["fuel_type"] == fuel]
        fig.add_trace(
            go.Bar(
                x=d["depot_code"],
                y=d["co2_kg_per_parcel"],
                name=fuel,
                marker=dict(color=SERIES[i], line=dict(width=2, color="#ffffff")),
                customdata=d[["vehicle_cost_per_parcel"]],
                hovertemplate="%{x} " + fuel + ": %{y:.3f} kg CO2e, van cost £%{customdata[0]:.2f} per parcel"
                "<extra></extra>",
            )
        )
    fig.update_layout(barmode="group")
    fig.update_yaxes(title="kg CO2e per parcel")
    return _layout(fig, 300)


def _rag_cell(key: str, value: float) -> str:
    kpi = KPIS[key]
    status = rag_status(kpi, value)
    style = f"--rag:{STATUS[status]}"
    return f'<td class="rag" style="{style}" title="{STATUS_LABEL[status]}">{format_value(kpi, value)}</td>'


def scorecard_table(con: duckdb.DuckDBPyConnection, period: Period, link: bool = True) -> str:
    """Depot scorecard for the latest month, every cell RAG-rated against its target."""
    rows = []
    depots = [r[0] for r in con.execute("SELECT depot_code FROM dim_depot ORDER BY depot_code").fetchall()]
    names = dict(con.execute("SELECT depot_code, depot_name FROM dim_depot").fetchall())
    for code in [*depots, None]:
        k = compute_kpis(con, code, period.start, period.end)
        label = "Network" if code is None else f"{code} · {html.escape(names[code])}"
        if code and link:
            label = f'<a href="depot-{code}.html">{label}</a>'
        cells = "".join(_rag_cell(key, k[key]) for key in SCORECARD_KPIS)
        style = ' style="font-weight:650"' if code is None else ""
        rows.append(f"<tr{style}><td>{label}</td><td>{k['parcels']:,.0f}</td>{cells}</tr>")
    head = "".join(f"<th>{html.escape(KPIS[k].label)}</th>" for k in SCORECARD_KPIS)
    return (
        f'<div class="wrap"><table><thead><tr><th>Depot</th><th>Parcels</th>{head}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _frame_table(df: pd.DataFrame, formats: dict[str, str]) -> str:
    head = "".join(f"<th>{html.escape(c.replace('_', ' ').capitalize())}</th>" for c in formats)
    body = []
    for row in df.to_dict("records"):  # keeps integer columns as integers, unlike iterrows
        cells = []
        for col, fmt in formats.items():
            v = row[col]
            cells.append(f"<td>{html.escape(fmt.format(v) if fmt else str(v))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        f'<div class="wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
    )


def _page(title: str, subtitle: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{CSS}</style>"
        '<script src="plotly.min.js"></script></head><body>'
        f"<header><h1>{html.escape(title)}</h1><p>{subtitle}</p></header><main>{body}</main></body></html>\n"
    )


def _card(title: str, content: str, note: str = "") -> str:
    note_html = f'<p class="note">{note}</p>' if note else ""
    return f'<section class="card"><h2>{html.escape(title)}</h2>{note_html}{content}</section>'


def depot_page(con: duckdb.DuckDBPyConnection, code: str, period: Period) -> str:
    """Drill-down page for one depot: tiles, trend versus network, routes, drivers and failures."""
    name = con.execute("SELECT depot_name FROM dim_depot WHERE depot_code = ?", [code]).fetchone()[0]
    trend = query_df(
        con, "SELECT * FROM v_weekly_trend WHERE depot_code IN (?, 'ALL') ORDER BY week_start", [code]
    )
    fig = go.Figure()
    for i, (c, label) in enumerate([(code, code), ("ALL", "Network")]):
        d = trend[trend["depot_code"] == c]
        fig.add_trace(
            go.Scatter(
                x=d["week_start"],
                y=d["on_time_rate"],
                name=f"{label} on-time",
                mode="lines+markers",
                line=dict(width=2, color=SERIES[i]),
                marker=dict(size=8, line=dict(width=2, color="#ffffff")),
                hovertemplate="w/c %{x|%d %b}: %{y:.1%}<extra>" + label + "</extra>",
            )
        )
    fig.add_hline(y=KPIS["on_time_rate"].target, line=dict(color="#9c9c9c", width=1, dash="dash"))
    fig.update_yaxes(tickformat=".0%")

    routes = query_df(
        con, "SELECT * FROM v_route_performance WHERE depot_code = ? ORDER BY rank_in_depot", [code]
    )
    drivers = query_df(
        con,
        """SELECT quartile, COUNT(*) AS drivers, AVG(first_attempt_rate) AS first_attempt_rate,
                  AVG(CASE WHEN employment_type = 'Agency' THEN 1.0 ELSE 0 END) AS agency_share,
                  AVG(tenure_months) AS avg_tenure
           FROM v_driver_league WHERE depot_code = ? GROUP BY quartile ORDER BY quartile""",
        [code],
    )
    body = (
        '<p><a href="index.html">← Network overview</a></p>'
        + _tiles(con, period, code)
        + _card(f"Weekly on-time delivery: {code} against the network", _div(_layout(fig)))
        + _card(
            "Routes",
            _frame_table(
                routes,
                {
                    "route_code": "",
                    "area_type": "",
                    "parcels": "{:,.0f}",
                    "first_attempt_rate": "{:.1%}",
                    "on_time_rate": "{:.1%}",
                    "cost_per_parcel": "£{:.2f}",
                    "vehicle_utilisation": "{:.0%}",
                    "parcels_per_hour": "{:.1f}",
                },
            ),
            "Whole period. Ranked by on-time rate.",
        )
        + '<div class="grid2">'
        + _card(
            "Driver first-attempt quartiles",
            _frame_table(
                drivers,
                {
                    "quartile": "Q{}",
                    "drivers": "{}",
                    "first_attempt_rate": "{:.1%}",
                    "agency_share": "{:.0%}",
                    "avg_tenure": "{:.0f} months",
                },
            ),
            "Q1 is the best quarter of drivers. A high agency share in Q4 points to onboarding and coaching.",
        )
        + _card("Why first attempts fail", _div(pareto_figure(con, code)))
        + "</div>"
    )
    return _page(
        f"{code} · {name}", f"Depot drill-down · tiles show {period.label} vs {period.prev_label}", body
    )


def build_dashboard(con: duckdb.DuckDBPyConnection, out_dir: str | Path) -> list[Path]:
    """Write index.html, one page per depot and plotly.min.js; returns the page paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "plotly.min.js").write_text(get_plotlyjs(), encoding="utf-8")
    period = latest_period(con)
    depots = [r[0] for r in con.execute("SELECT depot_code FROM dim_depot ORDER BY depot_code").fetchall()]
    first, last = con.execute("SELECT MIN(full_date), MAX(full_date) FROM v_kpi_depot_day").fetchone()

    body = (
        _tiles(con, period)
        + _card(
            "Weekly service trend",
            _div(trend_figure(con, depots)),
            "Use the menu at the top right to filter by depot. Dashed and dotted lines are the targets.",
        )
        + _card(
            f"Depot scorecard · {period.label}",
            scorecard_table(con, period),
            "Each cell is rated against its target (green on target, amber within 3%, red off target). "
            "Click a depot to drill down.",
        )
        + '<div class="grid2">'
        + _card("Why first attempts fail (network)", _div(pareto_figure(con)))
        + _card(
            "Overloaded vans miss their promises",
            _div(utilisation_figure(con)),
            "On-time rate of parcels by how full the van was that day.",
        )
        + "</div>"
        + _card("Fleet mix: emissions per parcel by depot", _div(fleet_figure(con)))
    )
    subtitle = (
        f"{first:%d %b %Y} – {last:%d %b %Y} · tiles show {period.label} vs {period.prev_label}"
        " · synthetic data"
    )
    pages = [out / "index.html"]
    pages[0].write_text(_page("Last-Mile Delivery Operations", subtitle, body), encoding="utf-8")
    for code in depots:
        path = out / f"depot-{code}.html"
        path.write_text(depot_page(con, code, period), encoding="utf-8")
        pages.append(path)
    return pages
