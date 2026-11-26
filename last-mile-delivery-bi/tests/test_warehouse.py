import duckdb
import pytest

from last_mile_delivery_bi.quality import run_checks
from last_mile_delivery_bi.warehouse import build_warehouse, create_views, query_df
from tests.conftest import SMALL


def test_all_views_created(con):
    names = create_views(con)
    assert names == [
        "v_kpi_depot_day",
        "v_depot_scorecard",
        "v_weekly_trend",
        "v_failure_pareto",
        "v_route_performance",
        "v_driver_league",
        "v_utilisation_bands",
        "v_fleet_mix",
    ]


def test_foreign_keys_are_enforced(con):
    with pytest.raises(duckdb.ConstraintException):
        con.execute("INSERT INTO dim_route VALUES (9999, 'XXX-R01', 999, 'Urban')")


def test_quality_checks_pass(con):
    results = run_checks(con)
    assert results and all(r.passed for r in results), [r for r in results if not r.passed]


def test_quality_checks_catch_a_broken_row(tmp_path):
    db = build_warehouse(tmp_path / "broken.duckdb", SMALL)
    db.execute("UPDATE fact_route_day SET total_cost = total_cost + 10 WHERE route_day_id = 1")
    failed = {r.name for r in run_checks(db) if not r.passed}
    assert failed == {"Route cost equals labour plus vehicle cost"}
    db.close()


def test_quality_checks_catch_a_route_day_with_no_parcels(tmp_path):
    # A Sunday route day with no parcels: the inner drill-across join would silently drop its cost.
    db = build_warehouse(tmp_path / "orphan.duckdb", SMALL)
    db.execute(
        """INSERT INTO fact_route_day
           SELECT 999999, 20260906, depot_key, route_key, driver_key, vehicle_key, planned_stops,
                  vehicle_capacity, km_driven, driver_hours, labour_cost, vehicle_cost, total_cost, co2_kg
           FROM fact_route_day WHERE route_day_id = 1"""
    )
    failed = {r.name for r in run_checks(db) if not r.passed}
    assert failed == {
        "Parcel count reconciles to route plans",
        "Drill-across view totals match the fact tables",
    }
    db.close()


def test_scorecard_matches_recalculation_from_facts(con):
    sql = """
        SELECT AVG(CASE WHEN f.on_time THEN 1.0 ELSE 0 END)
        FROM fact_delivery f JOIN dim_date d USING (date_key) JOIN dim_depot dp USING (depot_key)
        WHERE dp.depot_code = 'MAN' AND d.month = 10"""
    expected = con.execute(sql).fetchone()[0]
    got = con.execute(
        "SELECT on_time_rate FROM v_depot_scorecard WHERE depot_code = 'MAN' AND month_start = '2026-10-01'"
    ).fetchone()[0]
    assert got == pytest.approx(float(expected))


def test_scorecard_lag_and_rank(con):
    df = query_df(con, "SELECT * FROM v_depot_scorecard ORDER BY depot_code, month_start")
    first_months = df.groupby("depot_code").head(1)
    assert first_months["on_time_rate_mom"].isna().all()
    oct_ = df[df["month_start"].astype(str) == "2026-10-01"]
    assert sorted(oct_["on_time_rank"]) == [1, 2, 3, 4, 5, 6]
    assert oct_["share_of_network"].sum() == pytest.approx(1.0)


def test_drill_across_does_not_fan_out_costs(con):
    view_cost = float(con.execute("SELECT SUM(total_cost) FROM v_kpi_depot_day").fetchone()[0])
    fact_cost = float(
        con.execute(
            "SELECT (SELECT SUM(total_cost) FROM fact_route_day)"
            " + (SELECT SUM(redelivery_cost) FROM fact_delivery)"
        ).fetchone()[0]
    )
    assert view_cost == pytest.approx(fact_cost)


def test_failure_pareto_is_cumulative_and_network_is_sum_of_depots(con):
    df = query_df(con, "SELECT * FROM v_failure_pareto ORDER BY depot_code, reason_rank")
    for _, grp in df.groupby("depot_code"):
        assert grp["cumulative_share"].is_monotonic_increasing
        assert grp["cumulative_share"].iloc[-1] == pytest.approx(1.0)
    network = df[df["depot_code"] == "ALL"]["failures"].sum()
    assert network == df[df["depot_code"] != "ALL"]["failures"].sum()


def test_weekly_network_row_is_total_of_depots(con):
    df = query_df(con, "SELECT * FROM v_weekly_trend")
    totals = df[df["depot_code"] != "ALL"].groupby("week_start")["parcels"].sum()
    network = df[df["depot_code"] == "ALL"].set_index("week_start")["parcels"]
    assert (totals.sort_index() == network.sort_index()).all()


def test_overloaded_vans_have_worse_service(con):
    df = query_df(con, "SELECT * FROM v_utilisation_bands ORDER BY utilisation_band")
    assert df["on_time_rate"].iloc[-1] < df["on_time_rate"].iloc[0]
    assert df["out_of_time_rate"].iloc[-1] > df["out_of_time_rate"].iloc[0]


def test_driver_quartiles_cover_every_driver(con):
    df = query_df(con, "SELECT * FROM v_driver_league")
    drivers = con.execute("SELECT COUNT(*) FROM dim_driver").fetchone()[0]
    assert len(df) == drivers and set(df["quartile"]) == {1, 2, 3, 4}
