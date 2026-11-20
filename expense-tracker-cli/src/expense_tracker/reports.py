"""Output formats: aligned text tables, CSV/JSON export and a self-contained HTML report."""

from __future__ import annotations

import csv
import html
import json
from collections.abc import Callable, Iterable, Sequence
from typing import IO

from .analytics import Anomaly, CategoryStatus, TrendPoint
from .models import Expense
from .repository import MerchantStat

Formatter = Callable[[int], str]


def render_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(cell)) for w, cell in zip(widths, row, strict=True)]

    def fmt(cells: Sequence[str]) -> str:
        return " | ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True)).rstrip()

    return "\n".join([fmt(headers), "-+-".join("-" * w for w in widths), *map(fmt, rows)])


def summary_table(statuses: Sequence[CategoryStatus], money: Formatter) -> str:
    rows = []
    for s in statuses:
        flag = "OVER" if s.over_budget else ("AT RISK" if s.projected_over else "")
        rows.append(
            [
                s.category,
                money(s.spent),
                money(s.budget) if s.budget is not None else "-",
                f"{s.percent_used:.0f}%" if s.percent_used is not None else "-",
                money(s.projected),
                flag,
            ]
        )
    total = sum(s.spent for s in statuses)
    projected = sum(s.projected for s in statuses)
    rows.append(["TOTAL", money(total), "", "", money(projected), ""])
    return render_table(["Category", "Spent", "Budget", "Used", "Projected", "Status"], rows)


def trend_table(points: Sequence[TrendPoint], money: Formatter) -> str:
    rows = [
        [
            p.month,
            money(p.total),
            "-" if p.change_pct is None else f"{p.change_pct:+.1f}%",
            money(p.rolling_avg),
        ]
        for p in points
    ]
    return render_table(["Month", "Total", "vs prev", "3-mo avg"], rows)


def anomaly_table(anomalies: Sequence[Anomaly], money: Formatter) -> str:
    rows = [
        [
            str(a.expense.id),
            a.expense.spent_on.isoformat(),
            a.expense.category,
            a.expense.merchant,
            money(a.expense.amount_pence),
            money(a.median),
            f"{a.score:.1f}",
        ]
        for a in anomalies
    ]
    return render_table(["ID", "Date", "Category", "Merchant", "Amount", "Typical", "Score"], rows)


def _record(e: Expense) -> dict[str, object]:
    return {
        "id": e.id,
        "date": e.spent_on.isoformat(),
        "category": e.category,
        "merchant": e.merchant,
        "amount": f"{e.amount_pence / 100:.2f}",
        "source": e.source,
        "note": e.note,
    }


def export_csv(expenses: Iterable[Expense], fh: IO[str]) -> int:
    writer = csv.DictWriter(
        fh, fieldnames=["id", "date", "category", "merchant", "amount", "source", "note"]
    )
    writer.writeheader()
    n = 0
    for e in expenses:
        writer.writerow(_record(e))
        n += 1
    return n


def export_json(expenses: Iterable[Expense], fh: IO[str]) -> int:
    records = [_record(e) for e in expenses]
    json.dump(records, fh, indent=2)
    return len(records)


def _bar_chart(items: Sequence[tuple[str, int]], money: Formatter, budgets: dict[str, int]) -> str:
    if not items:
        return "<p>No spending this month.</p>"
    peak = max([v for _, v in items] + list(budgets.values())) or 1
    row_h, label_w, width = 28, 120, 560
    parts = [f'<svg viewBox="0 0 {label_w + width + 110} {row_h * len(items) + 8}" role="img">']
    for i, (label, value) in enumerate(items):
        y = i * row_h + 4
        w = value / peak * width
        over = label in budgets and value > budgets[label]
        colour = "#c2410c" if over else "#2563eb"
        parts.append(f'<text x="0" y="{y + 17}" class="lbl">{html.escape(label)}</text>')
        parts.append(
            f'<rect x="{label_w}" y="{y}" width="{w:.1f}" height="20" rx="3" fill="{colour}"/>'
        )
        if label in budgets:
            bx = label_w + budgets[label] / peak * width
            parts.append(
                f'<line x1="{bx:.1f}" x2="{bx:.1f}" y1="{y - 2}" y2="{y + 22}" class="budget"/>'
            )
        parts.append(f'<text x="{label_w + w + 6:.1f}" y="{y + 15}">{money(value)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _line_chart(points: Sequence[TrendPoint], money: Formatter) -> str:
    if len(points) < 2:
        return "<p>Not enough history for a trend.</p>"
    width, height, pad = 680, 200, 30
    peak = max(p.total for p in points) or 1
    step = (width - 2 * pad) / (len(points) - 1)

    def xy(i: int, v: int) -> str:
        return f"{pad + i * step:.1f},{height - pad - v / peak * (height - 2 * pad):.1f}"

    totals = " ".join(xy(i, p.total) for i, p in enumerate(points))
    rolling = " ".join(xy(i, p.rolling_avg) for i, p in enumerate(points))
    labels = "".join(
        f'<text x="{pad + i * step:.1f}" y="{height - 8}" class="tick">{p.month[2:]}</text>'
        for i, p in enumerate(points)
        if i % max(1, len(points) // 8) == 0
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img">'
        f'<polyline points="{totals}" class="total"/>'
        f'<polyline points="{rolling}" class="rolling"/>{labels}'
        f'<text x="{pad}" y="14" class="tick">peak {money(peak)}</text></svg>'
    )


def html_report(
    month: str,
    statuses: Sequence[CategoryStatus],
    trend: Sequence[TrendPoint],
    anomalies: Sequence[Anomaly],
    merchants: Sequence[MerchantStat],
    money: Formatter,
) -> str:
    budgets = {s.category: s.budget for s in statuses if s.budget is not None}
    bars = _bar_chart([(s.category, s.spent) for s in statuses if s.spent], money, budgets)
    esc = html.escape
    merchant_rows = "".join(
        f"<tr><td>{esc(m.merchant)}</td><td>{m.count}</td><td>{money(m.total_pence)}</td></tr>"
        for m in merchants
    )
    anomaly_rows = "".join(
        f"<tr><td>{a.expense.spent_on}</td><td>{esc(a.expense.merchant)}</td>"
        f"<td>{a.expense.category}</td><td>{money(a.expense.amount_pence)}</td>"
        f"<td>{money(a.median)}</td><td>{a.score:.1f}</td></tr>"
        for a in anomalies[:10]
    )
    total = sum(s.spent for s in statuses)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spending report {month}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#111}}
h1{{margin-bottom:.2rem}} .muted{{color:#555}} svg{{width:100%;height:auto}}
svg text{{font-size:12px;fill:#333}} .lbl{{font-weight:600}} .tick{{fill:#666;font-size:11px}}
.budget{{stroke:#111;stroke-width:2;stroke-dasharray:3 2}}
.total{{fill:none;stroke:#2563eb;stroke-width:2}}
.rolling{{fill:none;stroke:#9ca3af;stroke-width:2;stroke-dasharray:5 3}}
table{{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}}
td,th{{border-bottom:1px solid #e5e7eb;padding:.35rem .5rem;text-align:left}}
</style></head><body>
<h1>Spending report: {month}</h1>
<p class="muted">Total spent {money(total)} · dashed lines mark budgets, orange = over budget</p>
<h2>By category</h2>{bars}
<h2>Monthly trend</h2>
<p class="muted">Blue: monthly total · grey dashed: 3-month rolling average</p>
{_line_chart(trend, money)}
<h2>Top merchants</h2>
<table><tr><th>Merchant</th><th>Transactions</th><th>Total</th></tr>{merchant_rows}</table>
<h2>Unusual expenses</h2>
<table><tr><th>Date</th><th>Merchant</th><th>Category</th><th>Amount</th><th>Typical</th>
<th>Score</th></tr>{anomaly_rows or '<tr><td colspan="6">None detected</td></tr>'}</table>
</body></html>
"""
