from datetime import date

import pytest

from last_mile_delivery_bi.metrics import (
    KPIS,
    compute_kpis,
    format_value,
    kpi_by,
    kpi_definitions_markdown,
    rag_status,
)


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("on_time_rate", 0.90, "green"),
        ("on_time_rate", 0.86, "amber"),  # 2.3% below an 88% target
        ("on_time_rate", 0.80, "red"),
        ("cost_per_parcel", 2.00, "green"),  # lower is better
        ("cost_per_parcel", 2.10, "amber"),
        ("cost_per_parcel", 2.40, "red"),
        ("vehicle_utilisation", 0.80, "green"),
        ("vehicle_utilisation", 0.965, "red"),  # overloaded vans breach the ceiling
        ("parcels", 1000, "none"),
        ("on_time_rate", None, "none"),
    ],
)
def test_rag_status(key, value, expected):
    assert rag_status(KPIS[key], value) == expected


def test_network_kpis_are_ratios_of_sums(con):
    k = compute_kpis(con)
    parcels, fa, ot = con.execute(
        "SELECT COUNT(*), SUM(first_attempt_success::INT), SUM(on_time::INT) FROM fact_delivery"
    ).fetchone()
    hours, stops, cap = con.execute(
        "SELECT SUM(driver_hours), SUM(planned_stops), SUM(vehicle_capacity) FROM fact_route_day"
    ).fetchone()
    assert k["parcels"] == parcels
    assert k["first_attempt_rate"] == pytest.approx(fa / parcels)
    assert k["on_time_rate"] == pytest.approx(ot / parcels)
    assert k["parcels_per_hour"] == pytest.approx(parcels / float(hours))
    assert k["vehicle_utilisation"] == pytest.approx(stops / cap)


def test_filters_by_depot_and_date(con):
    oct_bhm = compute_kpis(con, "BHM", date(2026, 10, 1), date(2026, 10, 31))
    expected = con.execute(
        """SELECT COUNT(*) FROM fact_delivery JOIN dim_depot USING (depot_key) JOIN dim_date USING (date_key)
           WHERE depot_code = 'BHM' AND month = 10"""
    ).fetchone()[0]
    assert oct_bhm["parcels"] == expected
    assert compute_kpis(con, "ZZZ")["parcels"] is None


def test_rollup_is_volume_weighted_not_a_simple_average(con):
    by_depot = kpi_by(con, "depot_code", "on_time_rate")
    parcels = kpi_by(con, "depot_code", "parcels")
    weighted = sum(by_depot[d] * parcels[d] for d in by_depot) / sum(parcels.values())
    assert compute_kpis(con)["on_time_rate"] == pytest.approx(weighted)


def test_kpi_by_rejects_unknown_dimension(con):
    with pytest.raises(ValueError):
        kpi_by(con, "1; DROP TABLE fact_delivery", "parcels")


def test_format_value():
    assert format_value(KPIS["on_time_rate"], 0.8766) == "87.7%"
    assert format_value(KPIS["return_rate"], 0.0125) == "1.25%"
    assert format_value(KPIS["cost_per_parcel"], 2.1) == "£2.10"
    assert format_value(KPIS["parcels"], 493620) == "493,620"
    assert format_value(KPIS["parcels_per_hour"], 13.46) == "13.5"
    assert format_value(KPIS["co2_kg_per_parcel"], None) == "n/a"


def test_definitions_markdown_lists_every_kpi():
    md = kpi_definitions_markdown()
    assert all(k.label in md for k in KPIS.values())
    assert md.count("\n") == len(KPIS) + 2
