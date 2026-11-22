"""Semantic (metrics) layer: one definition per KPI, a dimension allowlist, RLS on every query.

Dashboards, the CLI and the validation suite all ask for numbers through ``query()``, so a
KPI has exactly one definition. Metrics on different facts (sales lines vs monthly targets)
are computed separately and joined on conformed dimensions ("drill-across").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb
import pandas as pd

from grocery_retail_bi.security import User


class SemanticError(ValueError):
    pass


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    fact: str  # "sales" | "target" | "derived"
    sql: str
    fmt: str  # "gbp" | "pct" | "int" | "num"
    description: str
    depends_on: tuple[str, ...] = ()


NOT_RET = "FILTER (WHERE NOT f.is_return)"

METRICS: dict[str, Metric] = {
    m.name: m
    for m in [
        Metric(
            "net_sales",
            "Net sales",
            "sales",
            "SUM(f.net_amount)",
            "gbp",
            "Sales after discounts, net of refunds (returns are negative lines). Ex-VAT.",
        ),
        Metric(
            "gross_margin",
            "Gross margin",
            "sales",
            "SUM(f.gross_margin)",
            "gbp",
            "Net sales minus cost of goods at the unit cost valid on the sale date.",
        ),
        Metric(
            "gross_margin_pct",
            "Gross margin %",
            "sales",
            "SUM(f.gross_margin) / NULLIF(SUM(f.net_amount), 0)",
            "pct",
            "Gross margin as a share of net sales.",
        ),
        Metric(
            "transactions",
            "Transactions",
            "sales",
            f"COUNT(DISTINCT f.basket_id) {NOT_RET}",
            "int",
            "Distinct sale baskets; refund-only baskets are excluded.",
        ),
        Metric(
            "atv",
            "Average transaction value",
            "sales",
            f"SUM(f.net_amount) {NOT_RET} / NULLIF(COUNT(DISTINCT f.basket_id) {NOT_RET}, 0)",
            "gbp",
            "Sales (before refunds) per transaction.",
        ),
        Metric("units", "Units", "sales", "SUM(f.quantity)", "int", "Units sold net of returns."),
        Metric(
            "units_per_basket",
            "Units per basket",
            "sales",
            f"SUM(f.quantity) {NOT_RET} / NULLIF(COUNT(DISTINCT f.basket_id) {NOT_RET}, 0)",
            "num",
            "Average units in a sale basket.",
        ),
        Metric(
            "promo_sales_share",
            "Promo sales share",
            "sales",
            "SUM(f.net_amount) FILTER (WHERE f.promo_sk > 0) / NULLIF(SUM(f.net_amount), 0)",
            "pct",
            "Share of net sales sold on promotion.",
        ),
        Metric(
            "discount_rate",
            "Discount rate",
            "sales",
            "SUM(f.discount_amount) / NULLIF(SUM(f.net_amount) + SUM(f.discount_amount), 0)",
            "pct",
            "Discount given as a share of gross (pre-discount) sales.",
        ),
        Metric(
            "return_rate",
            "Return rate",
            "sales",
            "-SUM(f.net_amount) FILTER (WHERE f.is_return) / "
            "NULLIF(SUM(f.net_amount) FILTER (WHERE NOT f.is_return), 0)",
            "pct",
            "Refunded value as a share of sales value.",
        ),
        Metric(
            "loyalty_share",
            "Loyalty sales share",
            "sales",
            "SUM(f.net_amount) FILTER (WHERE f.is_loyalty) / NULLIF(SUM(f.net_amount), 0)",
            "pct",
            "Share of net sales where a loyalty card was scanned.",
        ),
        Metric(
            "target_net_sales",
            "Target",
            "target",
            "SUM(t.target_net_sales)",
            "gbp",
            "Finance's monthly net sales target (store x month grain).",
        ),
        Metric(
            "vs_target_pct",
            "Vs target",
            "derived",
            "net_sales / target_net_sales - 1",
            "pct",
            "Net sales vs target. Only valid at month-or-coarser grain.",
            ("net_sales", "target_net_sales"),
        ),
    ]
}

# name -> (sql expression, facts it is available on, description)
DIMENSIONS: dict[str, tuple[str, frozenset[str], str]] = {
    "region": (
        "sc.region",
        frozenset({"sales", "target"}),
        "Store's region today (history restated to the current hierarchy)",
    ),
    "region_as_was": (
        "sv.region",
        frozenset({"sales", "target"}),
        "Store's region at the time of sale (SCD2 version)",
    ),
    "store_code": ("sc.store_code", frozenset({"sales", "target"}), "Store code"),
    "store_name": ("sc.store_name", frozenset({"sales", "target"}), "Store name"),
    "store_format": ("sv.format", frozenset({"sales", "target"}), "Format at time of sale"),
    "year": ("d.year", frozenset({"sales", "target"}), "Calendar year"),
    "quarter": ("d.year || '-Q' || d.quarter", frozenset({"sales", "target"}), "Quarter"),
    "year_month": ("d.year_month", frozenset({"sales", "target"}), "Calendar month"),
    "fiscal_year": ("d.fiscal_year", frozenset({"sales", "target"}), "Fiscal year (Mar-Feb)"),
    "iso_week": (
        "d.iso_year || '-W' || lpad(CAST(d.iso_week AS VARCHAR), 2, '0')",
        frozenset({"sales"}),
        "ISO week",
    ),
    "day_name": ("d.day_name", frozenset({"sales"}), "Day of week"),
    "category": ("p.category", frozenset({"sales"}), "Category at time of sale"),
    "subcategory": ("p.subcategory", frozenset({"sales"}), "Subcategory"),
    "own_label": ("p.own_label", frozenset({"sales"}), "Own-label flag"),
    "promotion": ("pr.promo_name", frozenset({"sales"}), "Promotion name"),
    "is_loyalty": ("f.is_loyalty", frozenset({"sales"}), "Loyalty card scanned"),
}

FROM = {
    "sales": """FROM mart.fact_sales_line f
        JOIN mart.dim_store sv ON sv.store_sk = f.store_sk
        JOIN mart.dim_store sc ON sc.store_code = sv.store_code AND sc.is_current
        JOIN mart.dim_product p ON p.product_sk = f.product_sk
        JOIN mart.dim_promotion pr ON pr.promo_sk = f.promo_sk
        JOIN mart.dim_date d ON d.date_key = f.date_key""",
    "target": """FROM mart.fact_store_target t
        JOIN mart.dim_store sv ON sv.store_sk = t.store_sk
        JOIN mart.dim_store sc ON sc.store_code = sv.store_code AND sc.is_current
        JOIN mart.dim_date d ON d.date_key = t.month_key""",
}


@dataclass(frozen=True)
class Query:
    metrics: tuple[str, ...]
    by: tuple[str, ...] = ()
    filters: tuple[tuple[str, tuple], ...] = ()
    date_from: date | None = None
    date_to: date | None = None


def _expand(metrics: list[str]) -> tuple[list[str], list[Metric]]:
    unknown = [m for m in metrics if m not in METRICS]
    if unknown:
        raise SemanticError(f"unknown metric(s): {unknown}. Known: {sorted(METRICS)}")
    base: list[str] = []
    for m in metrics:
        for dep in METRICS[m].depends_on or (m,):
            if METRICS[dep].fact != "derived" and dep not in base:
                base.append(dep)
    return base, [METRICS[m] for m in metrics if METRICS[m].fact == "derived"]


def compile_sql(
    fact: str,
    metrics: list[str],
    by: list[str],
    filters: dict[str, list],
    user: User,
    date_from: date | None,
    date_to: date | None,
) -> tuple[str, list]:
    for dim in list(by) + list(filters):
        if dim not in DIMENSIONS:
            raise SemanticError(f"unknown dimension {dim!r}. Known: {sorted(DIMENSIONS)}")
        if fact not in DIMENSIONS[dim][1]:
            raise SemanticError(f"dimension {dim!r} is not available for {fact} metrics")
    rls_sql, params = user.predicate("sc")
    where = [rls_sql]
    for dim, values in filters.items():
        if not values:
            raise SemanticError(f"filter on {dim!r} needs at least one value")
        where.append(f"{DIMENSIONS[dim][0]} IN ({', '.join('?' for _ in values)})")
        params.extend(values)
    if date_from:
        where.append("d.date >= ?")
        params.append(date_from)
    if date_to:
        where.append("d.date <= ?")
        params.append(date_to)
    select = [f"{DIMENSIONS[d][0]} AS {d}" for d in by]
    select += [f"{METRICS[m].sql} AS {m}" for m in metrics]
    sql = f"SELECT {', '.join(select)} {FROM[fact]} WHERE {' AND '.join(where)}"
    if by:
        sql += f" GROUP BY {', '.join(DIMENSIONS[d][0] for d in by)} ORDER BY {', '.join(by)}"
    return sql, params


def query(
    conn: duckdb.DuckDBPyConnection,
    metrics: list[str],
    user: User,
    by: list[str] | None = None,
    filters: dict[str, list] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> pd.DataFrame:
    by = list(by or [])
    filters = dict(filters or {})
    base, derived = _expand(metrics)
    frames = []
    for fact in ("sales", "target"):
        fact_metrics = [m for m in base if METRICS[m].fact == fact]
        if not fact_metrics:
            continue
        sql, params = compile_sql(fact, fact_metrics, by, filters, user, date_from, date_to)
        df = conn.execute(sql, params).df()
        for m in fact_metrics:
            df[m] = pd.to_numeric(df[m], errors="coerce").astype(float)
        frames.append(df)
    result = frames[0]
    for other in frames[1:]:
        result = (
            result.merge(other, on=by, how="outer") if by else pd.concat([result, other], axis=1)
        )
    for d in derived:
        result[d.name] = result.eval(d.sql)
    return result[by + metrics].reset_index(drop=True)


def scalar(conn: duckdb.DuckDBPyConnection, metric: str, user: User, **kwargs) -> float:
    df = query(conn, [metric], user, **kwargs)
    return float(df[metric].iloc[0]) if len(df) else 0.0


def lfl_growth(
    conn: duckdb.DuckDBPyConnection, user: User, start: date, end: date, by: list[str] | None = None
) -> pd.DataFrame:
    """Like-for-like net sales growth: this period vs the same dates last year, counting only
    stores trading for the whole of both periods (opened before last year's start, not closed
    before this period's end)."""
    by = list(by or [])
    ly_start, ly_end = start.replace(year=start.year - 1), end.replace(year=end.year - 1)
    lfl_stores = [
        r[0]
        for r in conn.execute(
            "SELECT store_code FROM mart.dim_store WHERE is_current AND opened_on <= ? "
            "AND (closed_on IS NULL OR closed_on >= ?)",
            [ly_start, end],
        ).fetchall()
    ]
    if not lfl_stores:
        return pd.DataFrame(columns=[*by, "net_sales_ty", "net_sales_ly", "lfl_growth"])
    f = {"store_code": lfl_stores}
    ty = query(conn, ["net_sales"], user, by, f, start, end).rename(
        columns={"net_sales": "net_sales_ty"}
    )
    ly = query(conn, ["net_sales"], user, by, f, ly_start, ly_end).rename(
        columns={"net_sales": "net_sales_ly"}
    )
    out = ty.merge(ly, on=by, how="outer") if by else pd.concat([ty, ly], axis=1)
    out["lfl_growth"] = out.net_sales_ty / out.net_sales_ly - 1
    return out


def fmt_value(metric: str, value: float) -> str:
    kind = METRICS[metric].fmt if metric in METRICS else "pct" if metric == "lfl_growth" else "num"
    if pd.isna(value):
        return "n/a"
    if kind == "gbp":
        return f"£{value:,.0f}" if abs(value) >= 100 else f"£{value:,.2f}"
    if kind == "pct":
        return f"{value:+.1%}" if metric in {"vs_target_pct", "lfl_growth"} else f"{value:.1%}"
    if kind == "int":
        return f"{value:,.0f}"
    return f"{value:,.2f}"
