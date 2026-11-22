"""Data-validation suite: reconcile dashboard numbers to source, check SCD2 and RLS integrity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb

from grocery_retail_bi.security import USERS, Role, User
from grocery_retail_bi.semantic import scalar

TOLERANCE = 0.01  # £0.01 on money totals


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    expected: str
    actual: str
    severity: str = "error"  # "error" fails the build, "warn" is reported only


def _one(conn: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    rows = conn.execute(sql, params or []).fetchall()
    return rows[0][0]


def _money(conn, sql, params=None) -> float:
    return float(_one(conn, sql, params) or 0)


def run_checks(
    conn: duckdb.DuckDBPyConnection,
    dashboard_kpis: dict[str, float] | None = None,
    l12m: tuple[date, date] = (date(2025, 11, 1), date(2026, 10, 31)),
) -> list[Check]:
    ceo = USERS["ceo"]
    checks: list[Check] = []

    def add(name, ok, expected, actual, severity="error"):
        checks.append(Check(name, bool(ok), str(expected), str(actual), severity))

    raw_distinct = _one(conn, "SELECT COUNT(DISTINCT line_id) FROM raw.sales_lines")
    stg = _one(conn, "SELECT COUNT(*) FROM stg.sales_lines")
    add("raw -> staging: one row per distinct line_id", raw_distinct == stg, raw_distinct, stg)

    fact = _one(conn, "SELECT COUNT(*) FROM mart.fact_sales_line")
    add("staging -> fact: row counts match", stg == fact, stg, fact)
    orphans = _one(
        conn,
        """SELECT COUNT(*) FROM stg.sales_lines s WHERE NOT EXISTS
                            (SELECT 1 FROM mart.fact_sales_line f WHERE f.line_id = s.line_id)""",
    )
    add("staging -> fact: no dropped lines", orphans == 0, 0, orphans)

    stg_sum = _money(conn, "SELECT SUM(net_amount) FROM stg.sales_lines")
    fact_sum = _money(conn, "SELECT SUM(net_amount) FROM mart.fact_sales_line")
    sem_sum = scalar(conn, "net_sales", ceo)
    add(
        "net sales: staging = fact",
        abs(stg_sum - fact_sum) < TOLERANCE,
        f"£{stg_sum:,.2f}",
        f"£{fact_sum:,.2f}",
    )
    add(
        "net sales: fact = semantic layer",
        abs(fact_sum - sem_sum) < TOLERANCE,
        f"£{fact_sum:,.2f}",
        f"£{sem_sum:,.2f}",
    )

    src_l12m = _money(
        conn,
        "SELECT SUM(net_amount) FROM stg.sales_lines WHERE sale_date BETWEEN ? AND ?",
        list(l12m),
    )
    if dashboard_kpis:
        dash = dashboard_kpis["net_sales"]
        add(
            "dashboard L12M net sales = source",
            abs(dash - src_l12m) < TOLERANCE,
            f"£{src_l12m:,.2f}",
            f"£{dash:,.2f}",
        )
        dash_all = dashboard_kpis["net_sales_all_time"]
        add(
            "dashboard all-time net sales = source",
            abs(dash_all - stg_sum) < TOLERANCE,
            f"£{stg_sum:,.2f}",
            f"£{dash_all:,.2f}",
        )
        src_tx = _one(
            conn,
            "SELECT COUNT(DISTINCT basket_id) FROM stg.sales_lines WHERE NOT "
            "is_return AND sale_date BETWEEN ? AND ?",
            list(l12m),
        )
        add(
            "dashboard L12M transactions = source",
            int(dashboard_kpis["transactions"]) == src_tx,
            src_tx,
            int(dashboard_kpis["transactions"]),
        )

    raw_tgt = _money(conn, "SELECT SUM(target_net_sales) FROM raw.store_targets")
    sem_tgt = scalar(conn, "target_net_sales", ceo)
    add(
        "targets: source = semantic layer",
        abs(raw_tgt - sem_tgt) < TOLERANCE,
        f"£{raw_tgt:,.2f}",
        f"£{sem_tgt:,.2f}",
    )

    regions = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT region FROM mart.dim_store WHERE is_current ORDER BY 1"
        ).fetchall()
    ]
    partition = sum(
        scalar(conn, "net_sales", User(f"rm_{r}", Role.REGIONAL, regions=(r,))) for r in regions
    )
    add(
        "RLS: regional views partition the executive total",
        abs(partition - sem_sum) < TOLERANCE,
        f"£{sem_sum:,.2f}",
        f"£{partition:,.2f}",
    )
    leaked = conn.execute(
        """SELECT COUNT(*) FROM (SELECT DISTINCT sc.store_code FROM mart.fact_sales_line f
           JOIN mart.dim_store sv ON sv.store_sk = f.store_sk
           JOIN mart.dim_store sc ON sc.store_code = sv.store_code AND sc.is_current
           WHERE sc.region = 'North West') x"""
    ).fetchall()[0][0]
    from grocery_retail_bi.semantic import query

    nw = query(conn, ["net_sales"], USERS["rm_north_west"], by=["store_code"])
    add(
        "RLS: North West manager sees exactly the North West stores",
        len(nw) == leaked,
        leaked,
        len(nw),
    )

    for dim, key in (("dim_store", "store_code"), ("dim_product", "product_code")):
        bad_current = _one(
            conn,
            f"""SELECT COUNT(*) FROM (SELECT {key} FROM mart.{dim}
                                     GROUP BY 1 HAVING COUNT(*) FILTER (WHERE is_current) <> 1)""",
        )
        add(f"SCD2 {dim}: exactly one current row per key", bad_current == 0, 0, bad_current)
        gaps = _one(
            conn,
            f"""SELECT COUNT(*) FROM (SELECT valid_from, lag(valid_to) OVER
                              (PARTITION BY {key} ORDER BY valid_from) AS prev_to
                              FROM mart.{dim}) WHERE prev_to IS NOT NULL
                              AND valid_from <> prev_to + 1""",
        )
        add(f"SCD2 {dim}: versions contiguous, no gaps or overlaps", gaps == 0, 0, gaps)

    pit = _one(
        conn,
        """SELECT COUNT(*) FROM mart.fact_sales_line f
                        JOIN mart.dim_store s USING (store_sk) JOIN mart.dim_date d USING (date_key)
                        WHERE d.date NOT BETWEEN s.valid_from AND s.valid_to""",
    )
    add("point-in-time: every sale joins the store version valid on its date", pit == 0, 0, pit)

    unknown = _one(
        conn, "SELECT AVG(CASE WHEN product_sk = -1 THEN 1 ELSE 0 END) FROM mart.fact_sales_line"
    )
    add(
        "unknown-product lines below 1% (mapped to sk -1)",
        unknown < 0.01,
        "< 1.00%",
        f"{unknown:.2%}",
        "warn",
    )
    gm = scalar(conn, "gross_margin_pct", ceo)
    add(
        "gross margin % within a plausible grocery range (15-45%)",
        0.15 <= gm <= 0.45,
        "15-45%",
        f"{gm:.1%}",
        "warn",
    )
    return checks


def report(checks: list[Check]) -> str:
    lines = ["| Check | Result | Expected | Actual |", "|---|---|---|---|"]
    for c in checks:
        mark = "✅" if c.passed else ("⚠️" if c.severity == "warn" else "❌")
        lines.append(f"| {c.name} | {mark} | {c.expected} | {c.actual} |")
    failed = [c for c in checks if not c.passed and c.severity == "error"]
    lines.append("")
    lines.append(f"**{len(checks) - len(failed)}/{len(checks)} checks passed.**")
    return "\n".join(lines)
