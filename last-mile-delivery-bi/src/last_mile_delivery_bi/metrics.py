"""Semantic layer: one governed definition per KPI, with targets and RAG status.

Every ratio KPI is defined as SUM(numerator) / SUM(denominator) over the additive
components in ``v_kpi_depot_day``. That keeps the number identical whether a user
looks at one depot for one week or the whole network for six months; averaging
pre-computed daily rates would weight a quiet Saturday the same as a busy Monday.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb

RAG_TOLERANCE = 0.03  # within 3% of target (relative) counts as amber


@dataclass(frozen=True)
class KPI:
    """A governed KPI definition."""

    key: str
    label: str
    numerator: str
    denominator: str | None
    unit: str  # "pct", "gbp", "num" or "kg"
    target: float | None
    higher_is_better: bool
    definition: str
    ceiling: float | None = None  # above this the KPI is red even if "higher is better"

    def sql(self) -> str:
        if self.denominator is None:
            return f"SUM({self.numerator})"
        return f"SUM({self.numerator}) / NULLIF(SUM({self.denominator}), 0)"


KPIS: dict[str, KPI] = {
    k.key: k
    for k in [
        KPI("parcels", "Parcels", "parcels", None, "num", None, True, "Parcels loaded for delivery."),
        KPI(
            "first_attempt_rate",
            "First-attempt delivery",
            "first_attempt_successes",
            "parcels",
            "pct",
            0.92,
            True,
            "Share of parcels delivered on the first attempt.",
        ),
        KPI(
            "on_time_rate",
            "On-time delivery",
            "on_time_parcels",
            "parcels",
            "pct",
            0.88,
            True,
            "Share of parcels delivered on the first attempt within the promised window.",
        ),
        KPI(
            "return_rate",
            "Return to sender",
            "returned",
            "parcels",
            "pct",
            0.010,
            False,
            "Share of parcels returned to the sender after three failed attempts.",
        ),
        KPI(
            "cost_per_parcel",
            "Cost per parcel",
            "total_cost",
            "delivered",
            "gbp",
            2.05,
            False,
            "Route cost (driver, van, energy) plus redelivery and return cost, per parcel delivered.",
        ),
        KPI(
            "parcels_per_hour",
            "Parcels per driver hour",
            "parcels",
            "driver_hours",
            "num",
            13.0,
            True,
            "Parcels handled per paid driver hour.",
        ),
        KPI(
            "vehicle_utilisation",
            "Van utilisation",
            "planned_stops",
            "capacity",
            "pct",
            0.75,
            True,
            "Parcels loaded as a share of van capacity. Above 92% vans run out of time and service falls.",
            ceiling=0.92,
        ),
        KPI(
            "co2_kg_per_parcel",
            "CO2e per parcel (kg)",
            "co2_kg",
            "parcels",
            "kg",
            0.15,
            False,
            "Tailpipe and grid emissions per parcel, from km driven and vehicle emission factors.",
        ),
    ]
}


def rag_status(kpi: KPI, value: float | None) -> str:
    """Return 'green', 'amber', 'red', or 'none' for a KPI value against its target."""
    if kpi.target is None or value is None:
        return "none"
    if kpi.ceiling is not None and value > kpi.ceiling:
        return "red"
    gap = (value - kpi.target) / kpi.target
    if not kpi.higher_is_better:
        gap = -gap
    if gap >= 0:
        return "green"
    return "amber" if gap >= -RAG_TOLERANCE else "red"


def format_value(kpi: KPI, value: float | None) -> str:
    """Format a KPI value for display."""
    if value is None:
        return "n/a"
    if kpi.unit == "pct":
        return f"{value:.1%}" if kpi.target is None or kpi.target >= 0.05 else f"{value:.2%}"
    if kpi.unit == "gbp":
        return f"£{value:,.2f}"
    if kpi.unit == "kg":
        return f"{value:.3f}"
    return f"{value:,.0f}" if value >= 100 else f"{value:,.1f}"


def _where(depot: str | None, start: date | None, end: date | None) -> tuple[str, list]:
    clauses, params = [], []
    if depot:
        clauses.append("depot_code = ?")
        params.append(depot)
    if start:
        clauses.append("full_date >= ?")
        params.append(start)
    if end:
        clauses.append("full_date <= ?")
        params.append(end)
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def compute_kpis(
    con: duckdb.DuckDBPyConnection,
    depot: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, float | None]:
    """Compute every KPI for an optional depot and inclusive date range."""
    where, params = _where(depot, start, end)
    select = ", ".join(f"{k.sql()} AS {k.key}" for k in KPIS.values())
    row = con.execute(f"SELECT {select} FROM v_kpi_depot_day {where}", params).fetchone()
    return {key: (None if v is None else float(v)) for key, v in zip(KPIS, row, strict=True)}


def kpi_by(con: duckdb.DuckDBPyConnection, dimension: str, kpi_key: str) -> dict[str, float]:
    """Compute one KPI grouped by a column of v_kpi_depot_day (e.g. depot_code, month_start)."""
    allowed = {"depot_code", "month_start", "week_start", "month_name"}
    if dimension not in allowed:
        raise ValueError(f"dimension must be one of {sorted(allowed)}")
    kpi = KPIS[kpi_key]
    rows = con.execute(
        f"SELECT {dimension}, {kpi.sql()} FROM v_kpi_depot_day GROUP BY 1 ORDER BY 1"
    ).fetchall()
    return {str(k): float(v) for k, v in rows}


def kpi_definitions_markdown() -> str:
    """Render the KPI catalogue as a Markdown table (used to build docs/KPI_DEFINITIONS.md)."""
    lines = [
        "| KPI | Definition | Formula | Target | Better when |",
        "|---|---|---|---|---|",
    ]
    for k in KPIS.values():
        formula = (
            f"`SUM({k.numerator})`"
            if k.denominator is None
            else f"`SUM({k.numerator}) / SUM({k.denominator})`"
        )
        target = "–" if k.target is None else format_value(k, k.target)
        better = "higher" if k.higher_is_better else "lower"
        if k.ceiling is not None:
            better += f" (red above {format_value(k, k.ceiling)})"
        lines.append(f"| {k.label} | {k.definition} | {formula} | {target} | {better} |")
    return "\n".join(lines) + "\n"
