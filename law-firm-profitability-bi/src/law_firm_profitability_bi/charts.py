"""Plotly figures. Each takes query results, so charts contain no business logic."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

BLUE, ORANGE, RED, GREY = "#2a78d6", "#eb6834", "#e34948", "#898781"
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e1e0d9", "#fcfcfb"


def _style(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title={"text": title, "font": {"size": 15, "color": INK}, "x": 0, "xref": "paper"},
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font={"family": "system-ui, sans-serif", "size": 12, "color": MUTED},
        margin={"l": 70, "r": 24, "t": 60, "b": 48},
        height=380,
        legend={"orientation": "h", "y": 1.08, "x": 1, "xanchor": "right"},
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, rangemode="tozero")
    return fig


def _label(amount: float, total: bool) -> str:
    sign = "" if total else "+" if amount >= 0 else "−"
    return f"{sign}£{abs(amount) / 1e6:.2f}m"


def bridge(steps: list[tuple[str, float, bool]], title: str) -> go.Figure:
    """Waterfall from (label, amount, is_total). Totals are neutral, rises blue, falls red."""
    fig = go.Figure(
        go.Waterfall(
            x=[s[0] for s in steps],
            y=[s[1] for s in steps],
            measure=["absolute" if i == 0 else "total" if s[2] else "relative"
                     for i, s in enumerate(steps)],
            text=[_label(a, t) for _, a, t in steps],
            textposition="outside",
            cliponaxis=False,
            connector={"line": {"color": GRID, "width": 1}},
            increasing={"marker": {"color": BLUE}},
            decreasing={"marker": {"color": RED}},
            totals={"marker": {"color": GREY}},
            hovertemplate="%{x}<br>£%{y:,.0f}<extra></extra>",
        )
    )  # fmt: skip
    fig.update_layout(showlegend=False)
    fig.update_yaxes(tickprefix="£", tickformat="~s")
    return _style(fig, title)


def lockup(rows: list[dict[str, Any]]) -> go.Figure:
    shown = [r for r in rows if r["lockup_days"] is not None]
    fig = go.Figure()
    for key, name, colour in (
        ("wip_days", "WIP days", BLUE),
        ("debtor_days", "Debtor days", ORANGE),
    ):
        fig.add_bar(
            x=[r["month"] for r in shown],
            y=[r[key] for r in shown],
            name=name,
            marker={"color": colour, "line": {"color": SURFACE, "width": 2}},
            hovertemplate="%{x|%b %Y}: %{y:.0f} days<extra>" + name + "</extra>",
        )
    fig.update_layout(barmode="stack", hovermode="x unified")
    return _style(fig, "Lock-up: days from doing the work to holding the cash")


def realisation(rows: list[dict[str, Any]]) -> go.Figure:
    ordered = sorted(rows, key=lambda r: r["billing_realisation_pct"] or 0)
    values = [r["billing_realisation_pct"] or 0 for r in ordered]
    fig = go.Figure(
        go.Bar(
            x=values,
            y=[r["unit_name"] for r in ordered],
            orientation="h",
            marker={"color": BLUE},
            text=[f"{v:.1f}%" for v in values],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
        )
    )
    fig = _style(fig, "Billing realisation by unit")
    fig.update_xaxes(range=[0, 112], ticksuffix="%")
    fig.update_layout(margin={"l": 160})
    return fig
