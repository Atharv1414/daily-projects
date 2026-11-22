"""Multi-page interactive dashboard (static Plotly HTML), rendered per user with RLS applied.

Every number on the page comes from the semantic layer. ``build_dashboard`` also returns the
headline KPI values it displayed so the validation suite can reconcile them with source data.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from grocery_retail_bi.security import User
from grocery_retail_bi.semantic import fmt_value, lfl_growth, query

PAGES = [
    ("overview", "Overview"),
    ("regions", "Regions & stores"),
    ("categories", "Categories & promotions"),
    ("trading", "Trading patterns"),
]
BLUE, GREY, GREEN, AMBER, RED = "#1f5fa8", "#9aa5b1", "#2e8540", "#d9822b", "#c23934"
L12M = (date(2025, 11, 1), date(2026, 10, 31))
YTD_TY = (date(2026, 1, 1), date(2026, 10, 31))


@dataclass
class DashboardResult:
    user: str
    pages: list[Path] = field(default_factory=list)
    kpis: dict[str, float] = field(default_factory=dict)


def _rag(v: float) -> str:
    if pd.isna(v):
        return GREY
    return GREEN if v >= 0 else AMBER if v >= -0.03 else RED


def _layout(fig: go.Figure, title: str, height: int = 420) -> go.Figure:
    fig.update_layout(
        title=title,
        height=height,
        template="plotly_white",
        margin=dict(l=50, r=20, t=60, b=40),
        font=dict(family="system-ui"),
        legend=dict(orientation="h", y=-0.15),
    )
    return fig


def _page(user: User, active: str, cards: str, figs: list[go.Figure], note: str = "") -> str:
    nav = " · ".join(
        f"<b>{label}</b>" if key == active else f"<a href='{key}.html'>{label}</a>"
        for key, label in PAGES
    )
    body = "".join(
        f.to_html(full_html=False, include_plotlyjs="cdn" if i == 0 else False)
        for i, f in enumerate(figs)
    )
    scope = {"executive": "All regions"}.get(user.role.value) or ", ".join(
        user.regions or user.stores
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Harvest &amp; Co trading dashboard</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f5f7fa;color:#1c2430}}
header{{background:#1c2430;color:#fff;padding:12px 20px}} header a{{color:#9cc3ff}}
main{{padding:16px 20px;max-width:1200px;margin:auto}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}}
.card{{background:#fff;border-radius:8px;padding:12px 14px;box-shadow:0 1px 2px #0002}}
.card .v{{font-size:24px;font-weight:600}} .card .l{{font-size:12px;color:#5b6675}}
.note{{font-size:12px;color:#5b6675}}
</style></head><body>
<header><b>Harvest &amp; Co</b> · trading dashboard · signed in as
<b>{html.escape(user.username)}</b> ({html.escape(user.role.value)}: {html.escape(scope)})
<br>{nav}</header><main>{cards}{body}<p class="note">{note}</p></main></body></html>"""


def _cards(items: list[tuple[str, str, str]]) -> str:
    cells = "".join(
        f"<div class='card'><div class='l'>{html.escape(label)}</div>"
        f"<div class='v' style='color:{colour}'>{html.escape(value)}</div></div>"
        for label, value, colour in items
    )
    return f"<div class='cards'>{cells}</div>"


def build_dashboard(conn: duckdb.DuckDBPyConnection, user: User, out_dir: Path) -> DashboardResult:
    out = out_dir / user.username
    out.mkdir(parents=True, exist_ok=True)
    res = DashboardResult(user.username)

    # --- Overview ---------------------------------------------------------------------
    head = query(
        conn,
        [
            "net_sales",
            "target_net_sales",
            "vs_target_pct",
            "gross_margin_pct",
            "atv",
            "transactions",
            "promo_sales_share",
        ],
        user,
        date_from=L12M[0],
        date_to=L12M[1],
    ).iloc[0]
    lfl = lfl_growth(conn, user, *YTD_TY)
    lfl_value = float(lfl.lfl_growth.iloc[0]) if len(lfl) else float("nan")
    all_time = query(conn, ["net_sales"], user).iloc[0]
    res.kpis = {k: float(head[k]) for k in head.index}
    res.kpis.update({"lfl_growth_ytd": lfl_value, "net_sales_all_time": float(all_time.net_sales)})
    cards = _cards(
        [
            ("Net sales (last 12 months)", fmt_value("net_sales", head.net_sales), BLUE),
            ("Vs target", fmt_value("vs_target_pct", head.vs_target_pct), _rag(head.vs_target_pct)),
            ("LFL growth (Jan-Oct YoY)", fmt_value("lfl_growth", lfl_value), _rag(lfl_value)),
            ("Gross margin %", fmt_value("gross_margin_pct", head.gross_margin_pct), BLUE),
            ("Avg transaction value", fmt_value("atv", head.atv), BLUE),
            ("Transactions", fmt_value("transactions", head.transactions), BLUE),
            ("Promo sales share", fmt_value("promo_sales_share", head.promo_sales_share), BLUE),
        ]
    )
    monthly = query(
        conn, ["net_sales", "target_net_sales", "gross_margin_pct"], user, by=["year_month"]
    )
    fig1 = go.Figure(
        [
            go.Bar(x=monthly.year_month, y=monthly.net_sales, name="Net sales", marker_color=BLUE),
            go.Scatter(
                x=monthly.year_month,
                y=monthly.target_net_sales,
                name="Target",
                mode="lines+markers",
                line=dict(color=AMBER, dash="dash"),
            ),
        ]
    )
    fig1.update_yaxes(tickprefix="£", tickformat=",.0f")
    fig2 = go.Figure(
        go.Scatter(
            x=monthly.year_month,
            y=monthly.gross_margin_pct,
            mode="lines+markers",
            line=dict(color=GREEN),
            name="GM%",
        )
    )
    fig2.update_yaxes(tickformat=".1%")
    path = out / "overview.html"
    path.write_text(
        _page(
            user,
            "overview",
            cards,
            [
                _layout(fig1, "Monthly net sales vs target"),
                _layout(fig2, "Gross margin % by month", 320),
            ],
            "Sampled EPOS extract; sales are ex-VAT, net of refunds. Region is the store's current "
            "region (history restated).",
        ),
        encoding="utf-8",
    )
    res.pages.append(path)

    # --- Regions & stores -------------------------------------------------------------
    reg = query(
        conn,
        ["net_sales", "target_net_sales", "vs_target_pct", "gross_margin_pct"],
        user,
        by=["region"],
        date_from=L12M[0],
        date_to=L12M[1],
    )
    fig3 = go.Figure(
        go.Bar(
            x=reg.region,
            y=reg.vs_target_pct,
            marker_color=[_rag(v) for v in reg.vs_target_pct],
            text=[fmt_value("vs_target_pct", v) for v in reg.vs_target_pct],
            customdata=reg.net_sales,
            hovertemplate="%{x}<br>vs target %{y:.1%}<br>sales £%{customdata:,.0f}",
        )
    )
    fig3.update_yaxes(tickformat=".0%")
    stores = query(
        conn,
        ["net_sales", "vs_target_pct", "gross_margin_pct", "atv"],
        user,
        by=["region", "store_name"],
        date_from=L12M[0],
        date_to=L12M[1],
    )
    fig4 = go.Figure()
    regions = sorted(stores.region.dropna().unique())
    for i, r in enumerate(regions):
        s = stores[stores.region == r].sort_values("net_sales")
        fig4.add_bar(
            y=s.store_name,
            x=s.net_sales,
            orientation="h",
            name=r,
            visible=i == 0,
            marker_color=[_rag(v) for v in s.vs_target_pct],
            customdata=s[["vs_target_pct", "gross_margin_pct", "atv"]].to_numpy(),
            hovertemplate="%{y}<br>£%{x:,.0f}<br>vs target %{customdata[0]:.1%}"
            "<br>GM %{customdata[1]:.1%}<br>ATV £%{customdata[2]:.2f}",
        )
    if len(regions) > 1:  # drill-down: pick a region to see its stores
        fig4.update_layout(
            updatemenus=[
                dict(
                    type="dropdown",
                    x=1,
                    y=1.15,
                    buttons=[
                        dict(
                            label=r,
                            method="update",
                            args=[{"visible": [j == i for j in range(len(regions))]}],
                        )
                        for i, r in enumerate(regions)
                    ],
                )
            ]
        )
    table = stores.sort_values("vs_target_pct")
    fig5 = go.Figure(
        go.Table(
            header=dict(
                values=["Region", "Store", "Net sales", "Vs target", "GM %", "ATV"],
                fill_color="#1c2430",
                font=dict(color="white"),
            ),
            cells=dict(
                values=[
                    table.region,
                    table.store_name,
                    [fmt_value("net_sales", v) for v in table.net_sales],
                    [fmt_value("vs_target_pct", v) for v in table.vs_target_pct],
                    [fmt_value("gross_margin_pct", v) for v in table.gross_margin_pct],
                    [fmt_value("atv", v) for v in table.atv],
                ],
                fill_color=[["#fff"] * len(table)] * 3
                + [
                    [
                        {GREEN: "#e3f2e6", AMBER: "#fdf0e1", RED: "#f9e0df", GREY: "#fff"}[_rag(v)]
                        for v in table.vs_target_pct
                    ]
                ]
                + [["#fff"] * len(table)] * 2,
            ),
        )
    )
    path = out / "regions.html"
    path.write_text(
        _page(
            user,
            "regions",
            "",
            [
                _layout(fig3, "Last 12 months vs target by region"),
                _layout(fig4, "Store drill-down (choose a region)", 520),
                _layout(fig5, "Store scorecard (worst vs target first)", 600),
            ],
        ),
        encoding="utf-8",
    )
    res.pages.append(path)

    # --- Categories & promotions ------------------------------------------------------
    cat = query(
        conn,
        ["net_sales", "gross_margin_pct", "promo_sales_share"],
        user,
        by=["category", "subcategory"],
        date_from=L12M[0],
        date_to=L12M[1],
    )
    cat = cat[cat.net_sales > 0]
    fig6 = go.Figure(
        go.Treemap(
            labels=list(cat.subcategory) + list(cat.category.unique()),
            parents=list(cat.category) + [""] * cat.category.nunique(),
            values=list(cat.net_sales)
            + [cat[cat.category == c].net_sales.sum() for c in cat.category.unique()],
            branchvalues="total",
            marker=dict(
                colors=list(cat.gross_margin_pct) + [None] * cat.category.nunique(),
                colorscale="RdYlGn",
                colorbar=dict(title="GM%", tickformat=".0%"),
            ),
            hovertemplate="%{label}<br>£%{value:,.0f}<extra></extra>",
        )
    )
    bycat = query(
        conn,
        ["net_sales", "gross_margin_pct", "promo_sales_share", "discount_rate"],
        user,
        by=["category"],
        date_from=L12M[0],
        date_to=L12M[1],
    )
    fig7 = go.Figure(
        go.Scatter(
            x=bycat.promo_sales_share,
            y=bycat.gross_margin_pct,
            mode="markers+text",
            text=bycat.category,
            textposition="top center",
            marker=dict(
                size=(bycat.net_sales / bycat.net_sales.max() * 50).clip(lower=8), color=BLUE
            ),
        )
    )
    fig7.update_xaxes(title="Promo sales share", tickformat=".0%")
    fig7.update_yaxes(title="Gross margin %", tickformat=".0%")
    path = out / "categories.html"
    path.write_text(
        _page(
            user,
            "categories",
            "",
            [
                _layout(fig6, "Category mix (size = net sales, colour = GM%)", 520),
                _layout(fig7, "Promotion reliance vs margin by category", 460),
            ],
            "Category is as recorded at the time of sale: Ready Meals moved from Frozen to "
            "'Food To Go' in Jan 2026.",
        ),
        encoding="utf-8",
    )
    res.pages.append(path)

    # --- Trading patterns -------------------------------------------------------------
    dow = query(conn, ["transactions", "atv"], user, by=["day_name"])
    order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    dow = dow.set_index("day_name").reindex(order).reset_index()
    fig8 = make_subplots(specs=[[{"secondary_y": True}]])
    fig8.add_bar(x=dow.day_name, y=dow.transactions, name="Transactions", marker_color=BLUE)
    fig8.add_scatter(
        x=dow.day_name, y=dow.atv, name="ATV", secondary_y=True, line=dict(color=AMBER)
    )
    heat = query(conn, ["net_sales"], user, by=["category", "year_month"])
    pivot = heat.pivot(index="category", columns="year_month", values="net_sales").fillna(0)
    share = pivot / pivot.sum(axis=0)
    fig9 = go.Figure(
        go.Heatmap(
            z=share.to_numpy(),
            x=share.columns,
            y=share.index,
            colorscale="Blues",
            colorbar=dict(tickformat=".0%"),
        )
    )
    path = out / "trading.html"
    path.write_text(
        _page(
            user,
            "trading",
            "",
            [
                _layout(fig8, "Transactions and ATV by day of week (all history)"),
                _layout(fig9, "Category share of monthly sales", 480),
            ],
        ),
        encoding="utf-8",
    )
    res.pages.append(path)
    return res
