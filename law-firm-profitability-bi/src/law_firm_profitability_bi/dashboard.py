"""Server-rendered dashboard pages, shared by the API and the static export."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import escape
from typing import Any
from urllib.parse import urlencode

import duckdb
import plotly.io as pio

from . import charts
from .config import CUTOFF
from .metrics import CATALOGUE, FY25, FY26, Metrics, Period
from .security import USERS, User, visible_units

_CSS = """
body{font:14px/1.5 system-ui,sans-serif;background:#f9f9f7;color:#0b0b0b;margin:0}
main{max-width:1180px;margin:auto;padding:20px 16px}
h1{font-size:22px;margin:0}h2{font-size:15px;margin:24px 0 8px}
nav,form{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:12px 0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.kpi,.card{background:#fcfcfb;border:1px solid #e1e0d9;border-radius:8px;padding:12px}
.kpi b{display:block;font-size:22px}.kpi span,.note{color:#52514e;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));gap:12px}
.card{min-width:0;overflow-x:auto}table{border-collapse:collapse;width:100%}
th,td{padding:6px 8px;text-align:right;border-bottom:1px solid #e1e0d9;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
"""


@dataclass(frozen=True)
class View:
    """What a page shows, plus how to build links that keep the current filters."""

    user: User
    unit_id: str
    period: Period
    reported_month: date
    link_base: str = "/"
    token: str = ""
    static: bool = False

    def link(self, unit_id: str) -> str:
        query = {
            "unit": unit_id,
            "start": self.period.start.isoformat(),
            "end": self.period.end.isoformat(),
            "month": self.reported_month.isoformat(),
        }
        return f"{self.link_base}?{urlencode(query)}"


def _money(value: float | None) -> str:
    return (
        "–" if value is None else f"£{value / 1e6:,.2f}m" if abs(value) >= 1e6 else f"£{value:,.0f}"
    )


def _num(value: float | None, suffix: str = "") -> str:
    return "–" if value is None else f"{value:,.1f}{suffix}"


def _cards(now: dict[str, Any], before: dict[str, Any] | None) -> str:
    specs = [
        ("net_value", "Net value recorded", _money),
        ("billed", "Billed", _money),
        ("cash", "Cash", _money),
        ("gross_margin_pct", "Gross margin", lambda v: _num(v, "%")),
        ("billing_realisation_pct", "Billing realisation", lambda v: _num(v, "%")),
        ("lockup_days", "Lock-up", lambda v: _num(v, " days")),
    ]
    out = []
    for key, label, fmt in specs:
        previous = "" if before is None else f"prior year {fmt(before[key])}"
        out.append(
            f'<div class="kpi" title="{escape(CATALOGUE[key])}"><span>{label}</span>'
            f"<b>{fmt(now[key])}</b><span>{previous}</span></div>"
        )
    return f'<div class="kpis">{"".join(out)}</div>'


def _table(headers: list[str], rows: list[list[str]]) -> str:
    """Cells must already be escaped or be trusted markup."""
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _filters(view: View, units: list[tuple[str, str, int]]) -> str:
    if view.static:
        return '<p class="note">Static export: run <code>law-bi serve</code> for filters.</p>'
    options = "".join(
        f'<option value="{u}"{" selected" if u == view.unit_id else ""}>'
        f"{'&nbsp;' * 3 * depth}{escape(name)}</option>"
        for u, name, depth in units
    )
    return (
        f'<form method="get"><label>Unit <select name="unit">{options}</select></label>'
        f'<label>From <input name="start" value="{view.period.start}"></label>'
        f'<label>To <input name="end" value="{view.period.end}"></label>'
        f'<label>Restated month <input name="month" value="{view.reported_month}"></label>'
        "<button>Apply</button></form>"
    )


def render(con: duckdb.DuckDBPyConnection, view: View) -> str:
    metrics = Metrics(con, view.user)
    unit = metrics.unit(view.unit_id)
    units = visible_units(con, view.user)
    name = next(n for u, n, _ in units if u == unit)
    now = metrics.kpis(view.period, unit)
    before = metrics.kpis(FY25, unit) if view.period == FY26 else None
    children = metrics.children(view.period, unit)

    figures = [
        charts.bridge(
            [(s["step"], s["amount"], s["kind"] == "total")
             for s in metrics.waterfall(view.period, unit)],
            "From standard value to cash, for bills issued",
        ),
        charts.lockup(metrics.lockup_trend(view.period, unit)),
        charts.realisation(children),
    ]  # fmt: skip
    if view.period == FY26:
        v = metrics.variance(FY25, FY26, unit)
        steps = [("FY25", v["base"], True)]
        steps += [(k.title(), v[k], False) for k in ("volume", "mix", "rate", "discount")]
        steps.append(("FY26", v["current"], True))
        figures.insert(1, charts.bridge(steps, "Why net value changed, FY25 to FY26"))
    month_end = _month_end(view.reported_month)
    restated_note = ""
    if month_end < CUTOFF:
        steps = metrics.restatement(view.reported_month, month_end, CUTOFF, unit)
        restated_note = _table(
            ["Step", "Amount", "Entries"],
            [[s["step"], f"£{s['amount']:,.0f}", "" if s["entries"] is None else str(s["entries"])]
             for s in steps],
        )  # fmt: skip

    parts = []
    for i, fig in enumerate(figures):
        js: str | bool = "cdn" if i == 0 else False
        html = pio.to_html(fig, full_html=False, include_plotlyjs=js, config={"responsive": True})
        parts.append(f'<div class="card">{html}</div>')

    def cell(row: dict[str, Any]) -> str:
        label = escape(row["unit_name"])
        linkable = not view.static and row["unit_id"] != unit
        return f'<a href="{escape(view.link(row["unit_id"]))}">{label}</a>' if linkable else label

    unit_table = _table(
        ["Unit", "Net value", "Billed", "Margin", "Realisation", "WIP days", "Debtor days"],
        [[cell(c), _money(c["net_value"]), _money(c["billed"]), _num(c["gross_margin_pct"], "%"),
          _num(c["billing_realisation_pct"], "%"), _num(c["wip_days"]), _num(c["debtor_days"])]
         for c in children],
    )  # fmt: skip
    listing = metrics.matters(unit, size=15)
    matter_table = _table(
        ["Matter", "Client", "Recorded", "Billed", "Unbilled", "Margin"],
        [[escape(m["matter_id"]), escape(m["client_name"]), _money(m["recorded"]),
          _money(m["billed"]), _money(m["unbilled"]), _num(m["margin_pct"], "%")]
         for m in listing["items"]],
    )  # fmt: skip
    hidden = listing["restricted"]
    wall = (
        f'<p class="note">{hidden["matters"]} matters behind information barriers: '
        f"{_money(hidden['recorded'])} recorded in total.</p>"
        if hidden["matters"]
        else ""
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Profitability: {escape(name)}</title><style>{_CSS}</style></head><body><main>"
        f"<h1>{escape(name)}</h1><p class='note'>{view.period.start:%b %Y} to "
        f"{view.period.end:%b %Y} · viewing as {escape(view.user.name)}</p>"
        f"{_filters(view, units)}{_cards(now, before)}<h2>Drivers</h2>"
        f"<div class='grid'>{''.join(parts)}</div><h2>Drill down</h2>"
        f"<div class='card'>{unit_table}</div>"
        f"<h2>Restatement of {view.reported_month:%B %Y}: first report against today</h2>"
        f"<div class='card'>{restated_note}</div><h2>Largest matters</h2>"
        f"<div class='card'>{matter_table}{wall}</div></main></body></html>"
    )


def _month_end(month: date) -> date:
    following = date(month.year + month.month // 12, month.month % 12 + 1, 1)
    return date.fromordinal(following.toordinal() - 1)


def static_views() -> dict[str, View]:
    month = date(2026, 4, 1)
    return {
        user_id: View(USERS[user_id], USERS[user_id].unit_id, FY26, month, static=True)
        for user_id in ("mp", "head_disputes")
    }
