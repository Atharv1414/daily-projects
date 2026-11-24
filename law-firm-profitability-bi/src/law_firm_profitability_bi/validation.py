"""Reconciliation checks. The build fails if any of them does."""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from .metrics import FY25, FY26, Metrics
from .security import USERS


@dataclass(frozen=True)
class Check:
    name: str
    detail: str
    ok: bool


# Each query returns the number of offending rows, or a difference that must be zero.
SQL_CHECKS = {
    "every raw row is loaded, duplicate or quarantined": """
        SELECT a.raw_rows - a.duplicate_rows - a.quarantined_rows
            - (SELECT count(*) FROM fact_time) FROM load_audit a""",
    "one rate-card version per timekeeper and day": """
        SELECT count(*) FROM dim_timekeeper a JOIN dim_timekeeper b
        ON a.timekeeper_id = b.timekeeper_id AND a.timekeeper_key < b.timekeeper_key
        AND a.valid_from < b.valid_to AND b.valid_from < a.valid_to""",
    "known-time intervals do not overlap": """
        SELECT count(*) FROM fact_time a JOIN fact_time b
        ON a.entry_id = b.entry_id AND a.version < b.version AND a.known_to > b.known_from""",
    "closing WIP equals recorded less cleared": """
        SELECT abs((SELECT sum(closing_wip) FROM fact_matter_month
            WHERE month_start = DATE '2026-10-01')
            - (SELECT sum(net_value) FROM v_time_current)
            + (SELECT sum(wip_cleared) FROM fact_bill_line))""",
    "closing debt equals billed less settled": """
        SELECT abs((SELECT sum(closing_debt) FROM fact_matter_month
            WHERE month_start = DATE '2026-10-01')
            - (SELECT sum(billed_amount) FROM fact_bill_line)
            + (SELECT sum(amount) FROM fact_receipt))""",
    "billed total ties to source": """
        SELECT abs((SELECT sum(billed_amount) FROM fact_bill_line)
            - (SELECT sum(billed_amount::DECIMAL(14, 2)) FROM raw.bill_lines))""",
    "cash total ties to source": """
        SELECT abs((SELECT sum(amount) FROM fact_receipt)
            - (SELECT sum(amount::DECIMAL(14, 2)) FROM raw.receipts))""",
    "no matter has negative WIP or debt": """
        SELECT count(*) FROM fact_matter_month WHERE closing_wip < 0 OR closing_debt < 0""",
    "no entry is billed twice": """
        SELECT count(*) - count(DISTINCT entry_id) FROM fact_bill_line""",
    "no bill is billed above its WIP value": """
        SELECT count(*) FROM fact_bill_line WHERE billed_amount > wip_cleared""",
    "every unit reaches the firm exactly once": """
        SELECT (SELECT count(*) FROM dim_org)
            - (SELECT count(*) FROM bridge_org WHERE ancestor_id = 'FIRM')""",
    "milestones are in order": """
        SELECT count(*) FROM fact_matter_lifecycle
        WHERE first_bill < first_time OR first_cash < first_bill""",
}


def run_checks(con: duckdb.DuckDBPyConnection) -> list[Check]:
    checks = []
    for name, sql in SQL_CHECKS.items():
        value = con.execute(sql).fetchone()[0]
        checks.append(Check(name, f"difference {value}", value == 0))

    firm = Metrics(con, USERS["mp"])
    for period, label in ((FY25, "FY25"), (FY26, "FY26")):
        total = firm.kpis(period)["net_value"]
        parts = sum(c["net_value"] for c in firm.children(period))
        checks.append(
            Check(f"{label} divisions add up to the firm", f"{total:,.2f} vs {parts:,.2f}",
                  abs(total - parts) < 0.01)
        )  # fmt: skip
    v = firm.variance(FY25, FY26)
    explained = v["base"] + v["volume"] + v["mix"] + v["rate"] + v["discount"]
    checks.append(
        Check("variance effects sum to the change", f"residual {explained - v['current']:.6f}",
              abs(explained - v["current"]) < 0.01)
    )  # fmt: skip
    w = {s["step"]: s["amount"] for s in firm.waterfall(FY26)}
    residual = sum(a for s, a in w.items() if s not in {"Billed", "Cash"}) - w["Cash"]
    checks.append(
        Check("waterfall steps reach cash", f"residual {residual:.2f}", abs(residual) < 0.05)
    )
    return checks
