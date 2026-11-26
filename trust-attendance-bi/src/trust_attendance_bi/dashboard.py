"""Multi-page static HTML dashboard (Plotly), with one page per school built under that head
teacher's row-level security, and every published table passed through suppression."""

from __future__ import annotations

import html
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from .charts import BLUE, NAMES, ORANGE
from .disclosure import suppress
from .semantic import METRICS, MetricQuery, Principal, SemanticLayer

TERMS = ["Autumn", "Spring", "Summer"]
CSS = """
body{font-family:system-ui,sans-serif;margin:0;background:#fcfcfb;color:#0b0b0b}
header{background:#14324f;color:#fff;padding:14px 24px}header a{color:#fff;margin-right:18px}
main{max-width:1100px;margin:0 auto;padding:20px 24px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.kpi{background:#fff;border:1px solid #e4e3df;padding:12px 16px}.kpi b{display:block;font-size:30px}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:6px 8px;border-bottom:1px solid #e4e3df;text-align:right}
th:first-child,td:first-child{text-align:left}td.c{color:#52514e;font-style:italic}
footer{color:#52514e;font-size:13px;padding:24px}
"""


def _fmt(v) -> str:
    if v == "c":
        return "c"
    if isinstance(v, float):
        return f"{v:.1f}"
    return html.escape(str(v))


def table_html(df: pd.DataFrame, caption: str) -> str:
    cols = [c for c in df.columns if c != "suppressed"]
    head = "".join(f"<th>{html.escape(c.replace('_', ' '))}</th>" for c in cols)
    rows = "".join(
        "<tr>"
        + "".join(f"<td class='{'c' if r[c] == 'c' else ''}'>{_fmt(r[c])}</td>" for c in cols)
        + "</tr>"
        for _, r in df.iterrows()
    )
    return f"<table><caption>{html.escape(caption)}</caption><tr>{head}</tr>{rows}</table>"


def _page(title: str, body: str, schools: list[str]) -> str:
    nav = "".join(f"<a href='school-{s}.html'>{NAMES[s]}</a>" for s in schools)
    return (
        f"<!doctype html><html lang='en-GB'><head><meta charset='utf-8'><title>{title}</title>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<script src='plotly.min.js'></script><style>{CSS}</style></head><body><header>"
        f"<a href='index.html'><b>Carrow Valley Academy Trust</b></a>"
        f"<a href='groups.html'>Pupil groups</a>"
        f"<a href='quality.html'>Data quality</a><br><small>Schools: {nav}</small></header>"
        f"<main><h1>{title}</h1>{body}</main><footer>Carrow Valley Academy Trust and its "
        f"schools are invented; all pupils are synthetic. <i>c</i> = suppressed: fewer than "
        f"5 pupils, or would "
        f"reveal a suppressed figure.</footer></body></html>"
    )


def _fig(fig: go.Figure) -> str:
    fig.update_layout(
        template="plotly_white",
        margin={"l": 50, "r": 20, "t": 50, "b": 40},
        height=380,
        font={"family": "system-ui"},
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _term_dropdown(fig: go.Figure, traces_per_view: int) -> None:
    views = ["Whole year", *TERMS]
    buttons = []
    for i, view in enumerate(views):
        visible = [j // traces_per_view == i for j in range(traces_per_view * len(views))]
        buttons.append({"label": view, "method": "update", "args": [{"visible": visible}]})
    fig.update_layout(updatemenus=[{"buttons": buttons, "x": 1, "xanchor": "right", "y": 1.18}])


def build(sl: SemanticLayer, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plotly.min.js").write_text(get_plotlyjs(), encoding="utf-8")
    schools = list(NAMES)
    written = []

    def write(name: str, title: str, body: str) -> None:
        path = out_dir / name
        path.write_text(_page(title, body, schools), encoding="utf-8")
        written.append(path)

    # ---- trust overview --------------------------------------------------------------
    kpi_metrics = [
        "attendance_rate",
        "persistent_absence_rate",
        "unauthorised_absence_rate",
        "pupils",
    ]
    kpi = sl.query(MetricQuery(kpi_metrics))[0].iloc[0]

    def tile(m: str) -> str:
        if m == "pupils":
            return (
                f"<div class='kpi'>Pupils<b>{int(kpi[m]):,}</b>"
                "<small>on roll at any point</small></div>"
            )
        unit = "%" if METRICS[m].unit == "%" else ""
        return (
            f"<div class='kpi'>{METRICS[m].label}<b>{kpi[m]:.1f}{unit}</b>"
            f"<small>{html.escape(METRICS[m].description)}</small></div>"
        )

    tiles = "".join(tile(m) for m in kpi_metrics)
    weekly, _ = sl.query(MetricQuery(["attendance_rate"], ["phase", "week"]))
    trend = go.Figure(
        [
            go.Scatter(
                x=weekly[weekly.phase == p].week,
                y=weekly[weekly.phase == p].attendance_rate,
                name=p,
                line={"color": c, "width": 2},
                hovertemplate="%{x|%d %b}: %{y:.1f}%",
            )
            for p, c in (("Primary", BLUE), ("Secondary", ORANGE))
        ]
    )
    trend.update_layout(title="Weekly attendance (%)")
    bars = go.Figure()
    for view in ["Whole year", *TERMS]:
        filters = {} if view == "Whole year" else {"term": view}
        df, _ = sl.query(
            MetricQuery(["attendance_rate", "persistent_absence_rate"], ["school"], filters)
        )
        bars.add_trace(
            go.Bar(
                x=[NAMES[s] for s in df.school],
                y=df.persistent_absence_rate,
                marker_color=BLUE,
                name="Persistent absence",
                visible=view == "Whole year",
                hovertemplate="%{x}: %{y:.1f}% persistently absent",
            )
        )
    bars.update_layout(title="Persistent absence by school (%)", showlegend=False)
    _term_dropdown(bars, 1)
    write(
        "index.html",
        "Trust overview, 2025/26",
        f"<div class='kpis'>{tiles}</div>{_fig(trend)}{_fig(bars)}",
    )

    # ---- pupil groups -----------------------------------------------------------------
    fsm, _ = sl.query(
        MetricQuery(["attendance_rate", "persistent_absence_rate", "pupils"], ["school", "fsm"])
    )
    gap = go.Figure(
        [
            go.Scatter(
                x=[NAMES[s] for s in fsm[fsm.fsm == f].school],
                y=fsm[fsm.fsm == f].attendance_rate,
                name=label,
                mode="markers",
                marker={"color": c, "size": 12, "line": {"color": "white", "width": 2}},
                hovertemplate="%{x}: %{y:.1f}%",
            )
            for f, label, c in ((False, "Not FSM", BLUE), (True, "FSM eligible", ORANGE))
        ]
    )
    gap.update_layout(title="Attendance by free school meal eligibility (%)")
    sen, _ = sl.query(
        MetricQuery(["pupils", "attendance_rate", "persistent_absence_rate"], ["school", "sen"])
    )
    sen["school"] = sen.school.map(NAMES)
    write(
        "groups.html",
        "Pupil groups",
        _fig(gap)
        + table_html(suppress(sen, ["school", "sen"]), "SEN status by school (suppressed)"),
    )

    # ---- one page per school, under that head's row-level security ------------------
    for s in schools:
        head = Principal("head", s)
        yg, _ = sl.query(
            MetricQuery(
                [
                    "pupils",
                    "attendance_rate",
                    "unauthorised_absence_rate",
                    "persistent_absence_rate",
                ],
                ["year_group", "fsm"],
            ),
            head,
        )
        wk, _ = sl.query(MetricQuery(["attendance_rate"], ["week"]), head)
        fig = go.Figure(
            go.Scatter(x=wk.week, y=wk.attendance_rate, line={"color": BLUE, "width": 2})
        )
        fig.update_layout(title=f"{NAMES[s]}: weekly attendance (%)")
        write(
            f"school-{s}.html",
            f"{NAMES[s]} (head teacher view)",
            _fig(fig)
            + table_html(
                suppress(yg, ["year_group", "fsm"]), "Year group by FSM eligibility (suppressed)"
            ),
        )

    # ---- data quality ------------------------------------------------------------------
    checks = sl.con.execute(
        "SELECT check_name, observed, limit_value, blocking, passed FROM dq_checks"
    ).df()
    quarantine = sl.con.execute(
        "SELECT reject_reason, count(*) AS rows FROM quarantine_marks GROUP BY 1 ORDER BY 2 DESC"
    ).df()
    runs = sl.con.execute("SELECT * FROM meta_runs ORDER BY started DESC LIMIT 5").df()
    write(
        "quality.html",
        "Data quality",
        table_html(checks, "Checks run with every build")
        + table_html(quarantine, "Quarantined marks")
        + table_html(runs.astype(str), "Recent builds"),
    )
    return written
