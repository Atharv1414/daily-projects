import pandas as pd

from last_mile_delivery_bi.data_generator import GeneratorConfig, build_dim_date, generate
from tests.conftest import SMALL


def test_same_seed_gives_identical_data(tables):
    again = generate(SMALL)
    for name, df in tables.items():
        pd.testing.assert_frame_equal(df, again[name], obj=name)


def test_different_seed_changes_data(tables):
    other = generate(GeneratorConfig(start=SMALL.start, end=SMALL.end, routes_per_depot=3, seed=8))
    assert not tables["fact_route_day"]["planned_stops"].equals(other["fact_route_day"]["planned_stops"])


def test_keys_are_unique_and_parcels_match_route_plans(tables):
    assert tables["fact_delivery"]["parcel_id"].is_unique
    assert tables["fact_route_day"]["route_day_id"].is_unique
    assert len(tables["fact_delivery"]) == tables["fact_route_day"]["planned_stops"].sum()


def test_no_deliveries_on_sundays(tables):
    sundays = tables["dim_date"].loc[tables["dim_date"]["day_of_week"] == 7, "date_key"]
    assert not tables["fact_route_day"]["date_key"].isin(sundays).any()


def test_dim_date_attributes():
    d = build_dim_date("2026-11-01", "2026-11-03").set_index("date_key")
    assert d.loc[20261101, "day_name"] == "Sun" and d.loc[20261101, "is_weekend"]
    assert str(d.loc[20261102, "week_start"]) == "2026-11-02"  # Monday
    assert str(d.loc[20261101, "week_start"]) == "2026-10-26"
    assert d.loc[20261103, "is_peak"] and d.loc[20261103, "month_name"] == "Nov 2026"


def test_built_in_business_effects():
    # Full route network over two months, so the area mix of each depot is representative.
    tables = generate(GeneratorConfig(start="2026-09-01", end="2026-10-31"))
    f = (
        tables["fact_delivery"]
        .merge(tables["dim_depot"], on="depot_key")
        .merge(tables["dim_driver"][["driver_key", "employment_type"]], on="driver_key")
    )
    by_depot = f.groupby("depot_code")["first_attempt_success"].mean()
    assert by_depot.idxmin() == "BHM"
    by_emp = f.groupby("employment_type")["first_attempt_success"].mean()
    assert by_emp["Agency"] < by_emp["Employed"]
    assert (f["on_time"] <= f["first_attempt_success"]).all()
