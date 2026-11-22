from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from grocery_retail_bi.security import USERS, AccessDenied, Role, User, get_user
from grocery_retail_bi.semantic import (
    DIMENSIONS,
    METRICS,
    SemanticError,
    compile_sql,
    fmt_value,
    lfl_growth,
    query,
    scalar,
)

CEO = USERS["ceo"]


def test_metric_catalog_complete():
    assert {"net_sales", "gross_margin_pct", "atv", "vs_target_pct"} <= set(METRICS)
    assert all(m.description for m in METRICS.values())


@pytest.mark.parametrize("metric", [m for m in METRICS if METRICS[m].fact != "derived"])
def test_every_metric_compiles_and_runs(conn, metric):
    assert len(query(conn, [metric], CEO)) == 1


def test_unknown_metric_and_dimension(conn):
    with pytest.raises(SemanticError):
        query(conn, ["profit_vibes"], CEO)
    with pytest.raises(SemanticError):
        query(conn, ["net_sales"], CEO, by=["colour"])
    with pytest.raises(SemanticError, match="not available"):
        query(conn, ["target_net_sales"], CEO, by=["category"])


def test_filter_values_are_bound_not_interpolated(conn):
    evil = "North West') OR TRUE --"
    sql, params = compile_sql("sales", ["net_sales"], [], {"region": [evil]}, CEO, None, None)
    assert evil not in sql and evil in params
    assert query(conn, ["net_sales"], CEO, filters={"region": [evil]}).net_sales.isna().all()


def test_drill_across_sales_and_targets(conn):
    df = query(conn, ["net_sales", "target_net_sales", "vs_target_pct"], CEO, by=["region"])
    assert df.target_net_sales.notna().all()
    row = df.iloc[0]
    assert row.vs_target_pct == pytest.approx(row.net_sales / row.target_net_sales - 1)


def test_ratio_metric_is_ratio_of_sums_not_average(conn):
    total = scalar(conn, "gross_margin_pct", CEO)
    parts = query(conn, ["gross_margin", "net_sales"], CEO, by=["region"])
    assert total == pytest.approx(parts.gross_margin.sum() / parts.net_sales.sum())


def test_rls_regional_scope(conn):
    nw = query(conn, ["net_sales"], USERS["rm_north_west"], by=["region"])
    assert list(nw.region) == ["North West"]
    # Asking for another region through a filter returns nothing, not someone else's data.
    leak = query(conn, ["net_sales"], USERS["rm_north_west"], filters={"region": ["London"]})
    assert leak.net_sales.isna().all() or leak.net_sales.iloc[0] == 0


def test_rls_store_manager_and_denials(conn):
    s = query(conn, ["net_sales"], USERS["sm_s105"], by=["store_code"])
    assert list(s.store_code) == ["S105"]
    with pytest.raises(AccessDenied):
        query(conn, ["net_sales"], USERS["nobody"])
    with pytest.raises(AccessDenied):
        get_user("mallory")


def test_rls_uses_current_region_for_history(conn):
    north = query(
        conn, ["net_sales"], USERS["rm_north"], by=["region_as_was"], date_to=date(2026, 3, 31)
    )
    # Sales made before the April 2026 realignment were booked under the old regions,
    # yet the North manager can see them because RLS keys on the current hierarchy.
    assert set(north.region_as_was) <= {"North East", "Yorkshire"} and len(north) > 0


def test_regions_partition_total(conn):
    regions = query(conn, ["net_sales"], CEO, by=["region"]).region
    total = sum(scalar(conn, "net_sales", User("x", Role.REGIONAL, regions=(r,))) for r in regions)
    assert total == pytest.approx(scalar(conn, "net_sales", CEO))


@settings(max_examples=15, deadline=None)
@given(
    st.dates(min_value=date(2025, 1, 1), max_value=date(2026, 10, 31)),
    st.integers(min_value=0, max_value=200),
)
def test_date_ranges_are_additive(conn, start, days):
    from datetime import timedelta

    end = min(start + timedelta(days=days), date(2026, 10, 31))
    mid = start + (end - start) / 2
    whole = scalar(conn, "net_sales", CEO, date_from=start, date_to=end)
    left = scalar(conn, "net_sales", CEO, date_from=start, date_to=mid)
    right = scalar(conn, "net_sales", CEO, date_from=mid + timedelta(days=1), date_to=end)
    import math

    def z(v):
        return 0.0 if math.isnan(v) else v

    assert z(whole) == pytest.approx(z(left) + z(right), abs=0.01)


def test_lfl_excludes_new_stores(conn):
    lfl = lfl_growth(conn, CEO, date(2026, 1, 1), date(2026, 10, 31))
    assert len(lfl) == 1 and -0.5 < lfl.lfl_growth.iloc[0] < 0.5
    new_store = conn.execute(
        "SELECT store_code FROM mart.dim_store WHERE is_current AND "
        "opened_on >= DATE '2026-01-01' LIMIT 1"
    ).fetchall()[0][0]
    only_new = lfl_growth(
        conn, User("sm", Role.STORE, stores=(new_store,)), date(2026, 1, 1), date(2026, 10, 31)
    )
    assert only_new.lfl_growth.isna().all()  # a new store has no like-for-like base


@pytest.mark.parametrize(
    ("metric", "value", "text"),
    [
        ("net_sales", 1234567.8, "£1,234,568"),
        ("atv", 12.345, "£12.35"),
        ("gross_margin_pct", 0.3021, "30.2%"),
        ("vs_target_pct", -0.017, "-1.7%"),
        ("lfl_growth", 0.09, "+9.0%"),
        ("transactions", 1234.0, "1,234"),
        ("net_sales", float("nan"), "n/a"),
    ],
)
def test_formatting(metric, value, text):
    assert fmt_value(metric, value) == text


def test_dimension_allowlist_has_sql_for_every_entry():
    assert all(expr and facts for expr, facts, _ in DIMENSIONS.values())
