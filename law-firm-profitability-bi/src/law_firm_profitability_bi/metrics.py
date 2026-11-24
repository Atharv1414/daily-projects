"""Metric definitions and the queries behind every dashboard number."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import duckdb

from .config import CUTOFF, FIRST_MONTH, BadRequest
from .security import User, resolve_unit

CATALOGUE = {
    "hours": "Active chargeable hours by date worked.",
    "standard_value": "Hours at the standard rate in force on the day worked.",
    "net_value": "Hours at the rate agreed with the client (standard less discount).",
    "billed": "Fees on bills dated in the period, excluding VAT.",
    "cash": "Cash received in the period, whenever billed.",
    "gross_margin_pct": "(net value - fee earner cost) / net value.",
    "billing_realisation_pct": "Billed / net value of the work those bills cleared.",
    "wip_days": "Closing WIP / last three months' billing x 91.",
    "debtor_days": "Closing debt / last three months' billing x 91.",
    "lockup_days": "WIP days + debtor days: how long work takes to become cash.",
}

_SCOPE = "unit_id IN (SELECT descendant_id FROM bridge_org WHERE ancestor_id = $unit)"
# Reproduces what the ledger contained at the end of a day.
_KNOWN = "is_active AND known_from <= $as_of AND known_to > $as_of"


@dataclass(frozen=True)
class Period:
    start: date
    end: date  # both are first-of-month; inclusive

    def __post_init__(self) -> None:
        if self.start.day != 1 or self.end.day != 1:
            raise BadRequest("periods are whole months: use the first day of a month")
        if self.start > self.end:
            raise BadRequest("period starts after it ends")
        if self.start < FIRST_MONTH or self.end > CUTOFF:
            raise BadRequest(f"data covers {FIRST_MONTH:%b %Y} to {CUTOFF:%b %Y}")


FY25 = Period(date(2024, 11, 1), date(2025, 10, 1))
FY26 = Period(date(2025, 11, 1), date(2026, 10, 1))


class Metrics:
    """Every method applies the user's organisation scope. There is no unscoped entry point."""

    def __init__(self, con: duckdb.DuckDBPyConnection, user: User) -> None:
        self._con = con
        self._user = user

    def _rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        # DuckDB rejects unused named parameters, so pass only those the query mentions.
        used = {k: v for k, v in params.items() if f"${k}" in sql}
        cursor = self._con.execute(sql, used)
        names = [c[0] for c in cursor.description]
        return [dict(zip(names, map(_plain, row), strict=True)) for row in cursor.fetchall()]

    def unit(self, unit_id: str | None) -> str:
        return resolve_unit(self._con, self._user, unit_id)

    def kpis(self, period: Period, unit_id: str | None = None) -> dict[str, float | None]:
        scope = dict(unit=self.unit(unit_id), start=period.start, end=period.end)
        worked = self._rows(
            f"""SELECT coalesce(sum(hours), 0) AS hours,
                coalesce(sum(standard_value), 0) AS standard_value,
                coalesce(sum(net_value), 0) AS net_value,
                coalesce(sum(cost_value), 0) AS cost
            FROM v_time_current WHERE {_SCOPE} AND work_month BETWEEN $start AND $end""",
            **scope,
        )[0]
        billing = self._rows(
            f"""SELECT coalesce(sum(billed_amount), 0) AS billed,
                coalesce(sum(wip_cleared), 0) AS cleared
            FROM fact_bill_line WHERE {_SCOPE} AND bill_month BETWEEN $start AND $end""",
            **scope,
        )[0]
        cash = self._rows(
            f"""SELECT coalesce(sum(amount), 0) AS cash FROM fact_receipt
            WHERE {_SCOPE} AND kind = 'cash' AND receipt_month BETWEEN $start AND $end""",
            **scope,
        )[0]
        lockup = self.lockup_trend(period, unit_id)[-1]
        return {
            "hours": worked["hours"],
            "standard_value": worked["standard_value"],
            "net_value": worked["net_value"],
            "billed": billing["billed"],
            "cash": cash["cash"],
            "gross_margin_pct": _pct(worked["net_value"] - worked["cost"], worked["net_value"]),
            "billing_realisation_pct": _pct(billing["billed"], billing["cleared"]),
            "wip_days": lockup["wip_days"],
            "debtor_days": lockup["debtor_days"],
            "lockup_days": lockup["lockup_days"],
        }

    def lockup_trend(self, period: Period, unit_id: str | None = None) -> list[dict[str, Any]]:
        rows = self._rows(
            f"""
            WITH unit_month AS (
                SELECT month_start, sum(closing_wip) AS wip, sum(closing_debt) AS debt,
                    sum(billed) AS billed
                FROM fact_matter_month WHERE {_SCOPE} GROUP BY month_start
            ), rolled AS (
                SELECT *, sum(billed) OVER (
                    ORDER BY month_start ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS billed_3m,
                    row_number() OVER (ORDER BY month_start) AS months
                FROM unit_month
            )
            SELECT month_start AS month, wip, debt,
                -- The first two months lack a full three-month base.
                CASE WHEN months >= 3 THEN wip / nullif(billed_3m, 0) * 91 END AS wip_days,
                CASE WHEN months >= 3 THEN debt / nullif(billed_3m, 0) * 91 END AS debtor_days
            FROM rolled WHERE month_start BETWEEN $start AND $end ORDER BY month_start
            """,
            unit=self.unit(unit_id),
            start=period.start,
            end=period.end,
        )
        for row in rows:
            parts = (row["wip_days"], row["debtor_days"])
            row["lockup_days"] = None if None in parts else sum(parts)
        empty = {"wip": 0, "debt": 0, "wip_days": None, "debtor_days": None, "lockup_days": None}
        return rows or [{"month": period.end.isoformat(), **empty}]

    def waterfall(self, period: Period, unit_id: str | None = None) -> list[dict[str, Any]]:
        """Follows bills issued in the period from standard value down to cash, so that every
        step concerns the same hours (a cohort, not a mix of periods)."""
        r = self._rows(
            f"""
            WITH lines AS (
                SELECT * FROM fact_bill_line
                WHERE {_SCOPE} AND bill_month BETWEEN $start AND $end
            ), settled AS (
                SELECT coalesce(sum(amount) FILTER (kind = 'cash'), 0) AS cash,
                    coalesce(sum(amount) FILTER (kind = 'bad_debt'), 0) AS bad_debt
                FROM fact_receipt WHERE bill_id IN (SELECT bill_id FROM lines)
            )
            SELECT coalesce(sum(standard_value), 0) AS standard,
                coalesce(sum(wip_cleared), 0) AS net,
                coalesce(sum(billed_amount), 0) AS billed,
                any_value(cash) AS cash, any_value(bad_debt) AS bad_debt
            FROM settled LEFT JOIN lines ON true
            """,
            unit=self.unit(unit_id),
            start=period.start,
            end=period.end,
        )[0]
        steps = [
            ("Standard value", r["standard"], "total"),
            ("Agreed discounts", r["net"] - r["standard"], "step"),
            ("Billing write-downs", r["billed"] - r["net"], "step"),
            ("Billed", r["billed"], "total"),
            ("Bad debt", -r["bad_debt"], "step"),
            ("Still owed", -(r["billed"] - r["cash"] - r["bad_debt"]), "step"),
            ("Cash", r["cash"], "total"),
        ]
        return [
            {"step": s, "amount": round(a, 2), "kind": k, "pct_of_standard": _pct(a, r["standard"])}
            for s, a, k in steps
        ]

    def variance(
        self, base: Period, current: Period, unit_id: str | None = None
    ) -> dict[str, float]:
        """Splits the change in net value into volume, grade mix, rate and discount."""
        rows = self._rows(
            f"""
            SELECT grade,
                coalesce(sum(hours) FILTER (work_month BETWEEN $b0 AND $b1), 0) AS h0,
                coalesce(sum(standard_value) FILTER (work_month BETWEEN $b0 AND $b1), 0) AS s0,
                coalesce(sum(net_value) FILTER (work_month BETWEEN $b0 AND $b1), 0) AS n0,
                coalesce(sum(hours) FILTER (work_month BETWEEN $c0 AND $c1), 0) AS h1,
                coalesce(sum(standard_value) FILTER (work_month BETWEEN $c0 AND $c1), 0) AS s1,
                coalesce(sum(net_value) FILTER (work_month BETWEEN $c0 AND $c1), 0) AS n1
            FROM v_time_current WHERE {_SCOPE} GROUP BY grade
            """,
            unit=self.unit(unit_id),
            b0=base.start,
            b1=base.end,
            c0=current.start,
            c1=current.end,
        )
        return decompose(rows)

    def restatement(
        self, month: date, reported_on: date, restated_on: date, unit_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Explains why a month's recorded value differs from what was first reported."""
        if reported_on >= restated_on:
            raise BadRequest("restated_on must be after reported_on")
        Period(month, month)
        rows = self._rows(
            f"""
            WITH before AS (
                SELECT * FROM fact_time WHERE work_month = $month AND is_active
                AND known_from <= $first AND known_to > $first
            ), after AS (
                SELECT * FROM fact_time WHERE work_month = $month AND is_active
                AND known_from <= $second AND known_to > $second
            ), paired AS (
                SELECT b.net_value AS value_before, a.net_value AS value_after,
                    b.unit_id AS unit_before, a.unit_id AS unit_after,
                    CASE WHEN b.entry_id IS NULL THEN 'Late posted'
                        WHEN a.entry_id IS NULL THEN 'Voided'
                        WHEN a.matter_id <> b.matter_id THEN 'Matter transfers'
                        WHEN a.net_value <> b.net_value THEN 'Hours corrected'
                        ELSE 'Unchanged' END AS reason
                FROM before b FULL JOIN after a ON a.entry_id = b.entry_id
            ), scoped AS (
                SELECT reason,
                    CASE WHEN {_SCOPE.replace("unit_id", "unit_before", 1)}
                        THEN value_before ELSE 0 END AS v0,
                    CASE WHEN {_SCOPE.replace("unit_id", "unit_after", 1)}
                        THEN value_after ELSE 0 END AS v1
                FROM paired
            )
            SELECT reason, count(*) FILTER (v0 <> 0 OR v1 <> 0) AS entries,
                sum(v0) AS before_value, sum(v1) AS after_value
            FROM scoped GROUP BY reason
            """,
            month=month,
            first=reported_on,
            second=restated_on,
            unit=self.unit(unit_id),
        )
        by_reason = {r["reason"]: r for r in rows}
        opening = sum(r["before_value"] for r in rows)
        out = [{"step": "As reported", "amount": round(opening, 2), "entries": None}]
        for reason in ("Late posted", "Hours corrected", "Matter transfers", "Voided"):
            r = by_reason.get(reason, {"before_value": 0, "after_value": 0, "entries": 0})
            amount = round(r["after_value"] - r["before_value"], 2)
            out.append({"step": reason, "amount": amount, "entries": r["entries"]})
        closing = round(sum(r["after_value"] for r in rows), 2)
        return [*out, {"step": "Restated", "amount": closing, "entries": None}]

    def recorded_as_of(self, month: date, as_of: date, unit_id: str | None = None) -> float:
        return self._rows(
            f"""SELECT coalesce(sum(net_value), 0) AS value FROM fact_time
            WHERE {_SCOPE} AND {_KNOWN} AND work_month = $month""",
            unit=self.unit(unit_id),
            as_of=as_of,
            month=month,
        )[0]["value"]

    def children(self, period: Period, unit_id: str | None = None) -> list[dict[str, Any]]:
        """One row per direct child unit (or the unit itself if it has none), for drill-down."""
        parent = self.unit(unit_id)
        kids = [
            r["unit_id"]
            for r in self._rows(
                "SELECT unit_id FROM dim_org WHERE parent_id = $unit ORDER BY unit_name",
                unit=parent,
            )
        ]
        names = {
            r["unit_id"]: r["unit_name"]
            for r in self._rows("SELECT unit_id, unit_name FROM dim_org")
        }
        return [
            {"unit_id": u, "unit_name": names[u], **self.kpis(period, u)} for u in kids or [parent]
        ]

    def matters(
        self, unit_id: str | None = None, page: int = 1, size: int = 20, sort: str = "recorded"
    ) -> dict[str, Any]:
        """Matter profitability. Matters behind an information barrier are collapsed into one
        line unless the user is on the wall list; under three of them, amounts are withheld."""
        if sort not in {"recorded", "billed", "margin_pct", "unbilled"}:
            raise BadRequest(f"cannot sort by {sort!r}")
        if page < 1 or not 1 <= size <= 100:
            raise BadRequest("page must be >= 1 and size between 1 and 100")
        base = f"""
            WITH scoped AS (
                SELECT l.*, c.client_name,
                    l.is_walled AND NOT EXISTS (
                        SELECT 1 FROM dim_wall w
                        WHERE w.matter_id = l.matter_id AND w.user_id = $user
                    ) AS restricted
                FROM fact_matter_lifecycle l JOIN dim_client c USING (client_id)
                WHERE {_SCOPE} AND recorded > 0
            )
        """
        params = dict(unit=self.unit(unit_id), user=self._user.user_id)
        rows = self._rows(
            base
            + f"""SELECT matter_id, client_name, unit_id, recorded, billed, cash,
                    recorded - billed AS unbilled,
                    (recorded - cost) / recorded * 100 AS margin_pct,
                    days_to_bill, days_to_cash, count(*) OVER () AS total
                FROM scoped WHERE NOT restricted
                ORDER BY {sort} DESC, matter_id LIMIT $size OFFSET $offset""",
            **params,
            size=size,
            offset=(page - 1) * size,
        )
        hidden = self._rows(
            base
            + """SELECT count(*) AS matters, coalesce(sum(recorded), 0) AS recorded
                FROM scoped WHERE restricted""",
            **params,
        )[0]
        if hidden["matters"] < 3:
            hidden["recorded"] = None
        total = rows[0]["total"] if rows else 0
        for row in rows:
            del row["total"]
        return {"page": page, "size": size, "total": total, "items": rows, "restricted": hidden}

    def lifecycle(self, unit_id: str | None = None) -> list[dict[str, Any]]:
        """Median days between milestones by unit, over matters that reached each milestone."""
        return self._rows(
            f"""SELECT o.unit_name AS unit, count(*) AS matters,
                median(days_to_time) AS days_to_time, median(days_to_bill) AS days_to_bill,
                median(days_to_cash) AS days_to_cash
            FROM fact_matter_lifecycle l JOIN dim_org o USING (unit_id)
            WHERE l.{_SCOPE} GROUP BY o.unit_name ORDER BY o.unit_name""",
            unit=self.unit(unit_id),
        )


def decompose(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Exact price-volume-mix split: the four effects always sum to the total change.

    volume   change in total hours at the base average value per hour
    mix      moving hours between grades
    rate     standard rate per grade, at the base discount
    discount agreed discount per grade, at the new standard rate
    A grade with no base hours has no base price, so all of its value is volume and mix.
    """
    base = sum(r["n0"] for r in rows)
    current = sum(r["n1"] for r in rows)
    h0, h1 = sum(r["h0"] for r in rows), sum(r["h1"] for r in rows)
    volume = (h1 - h0) * base / h0 if h0 else 0.0
    quantity = rate = discount = 0.0
    for r in rows:
        net1 = r["n1"] / r["h1"] if r["h1"] else 0.0
        if r["h0"] <= 0:
            quantity += r["n1"]
            continue
        net0 = r["n0"] / r["h0"]
        quantity += (r["h1"] - r["h0"]) * net0
        if r["h1"] > 0:
            std0, std1 = r["s0"] / r["h0"], r["s1"] / r["h1"]
            mid = std1 * (net0 / std0 if std0 else 0.0)
            rate += r["h1"] * (mid - net0)
            discount += r["h1"] * (net1 - mid)
    return {
        "base": base,
        "volume": volume,
        "mix": quantity - volume,
        "rate": rate,
        "discount": discount,
        "current": current,
    }


def _plain(value: Any) -> Any:
    """Decimals and dates to JSON-friendly types."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return float(value)


def _pct(part: float, whole: float) -> float | None:
    return part / whole * 100 if whole else None
