"""Data quality and reconciliation checks run after every load."""

from __future__ import annotations

from dataclasses import dataclass

import duckdb


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


CHECKS: list[tuple[str, str]] = [
    (
        "Parcel count reconciles to route plans",
        "SELECT (SELECT COUNT(*) FROM fact_delivery) - (SELECT SUM(planned_stops) FROM fact_route_day)",
    ),
    (
        "Every parcel matches its route day's depot, route, driver and van",
        """SELECT COUNT(*) FROM fact_delivery f JOIN fact_route_day r USING (route_day_id)
           WHERE f.depot_key <> r.depot_key OR f.route_key <> r.route_key
              OR f.driver_key <> r.driver_key OR f.vehicle_key <> r.vehicle_key
              OR f.date_key <> r.date_key""",
    ),
    (
        "Failure reason present exactly when the first attempt failed",
        """SELECT COUNT(*) FROM fact_delivery
           WHERE (first_attempt_success AND failure_reason IS NOT NULL)
              OR (NOT first_attempt_success AND failure_reason IS NULL)""",
    ),
    (
        "On-time parcels are a subset of first-attempt deliveries",
        "SELECT COUNT(*) FROM fact_delivery WHERE on_time AND NOT first_attempt_success",
    ),
    (
        "Drivers and vans only work routes in their own depot",
        """SELECT COUNT(*) FROM fact_route_day r
           JOIN dim_driver d USING (driver_key) JOIN dim_vehicle v USING (vehicle_key)
           WHERE d.depot_key <> r.depot_key OR v.depot_key <> r.depot_key""",
    ),
    (
        "Route cost equals labour plus vehicle cost",
        "SELECT COUNT(*) FROM fact_route_day WHERE ABS(total_cost - labour_cost - vehicle_cost) > 0.02",
    ),
    (
        "Drill-across view totals match the fact tables",
        """SELECT ABS((SELECT SUM(parcels) FROM v_kpi_depot_day) - (SELECT COUNT(*) FROM fact_delivery))
                + ABS((SELECT SUM(total_cost) FROM v_kpi_depot_day)
                      - (SELECT SUM(total_cost) FROM fact_route_day)
                      - (SELECT SUM(redelivery_cost) FROM fact_delivery))""",
    ),
]


def run_checks(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Run every check; each query returns a count of violations, where 0 means pass."""
    results = []
    for name, sql in CHECKS:
        violations = float(con.execute(sql).fetchone()[0] or 0)
        passed = abs(violations) < 0.01
        detail = "ok" if passed else f"{violations:,.2f} violations"
        results.append(CheckResult(name, passed, detail))
    return results
