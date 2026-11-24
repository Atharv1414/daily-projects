from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from law_firm_profitability_bi.config import AccessDenied, BadRequest
from law_firm_profitability_bi.metrics import CATALOGUE, FY25, FY26, Metrics, Period, decompose
from law_firm_profitability_bi.security import USERS

APRIL = date(2026, 4, 1)
REPORTED, RESTATED = date(2026, 4, 30), date(2026, 10, 31)

hours = st.one_of(st.just(0.0), st.floats(1, 10_000))
rate = st.floats(50, 900)
discount = st.floats(0, 0.5)


def grade_row(h0, h1, r0, r1, d0, d1):
    return {
        "h0": h0, "s0": h0 * r0, "n0": h0 * r0 * (1 - d0),
        "h1": h1, "s1": h1 * r1, "n1": h1 * r1 * (1 - d1),
    }  # fmt: skip


@given(
    st.lists(
        st.builds(grade_row, hours, hours, rate, rate, discount, discount), min_size=1, max_size=6
    )
)
def test_variance_is_always_exact(rows):
    v = decompose(rows)
    explained = v["base"] + v["volume"] + v["mix"] + v["rate"] + v["discount"]
    assert explained == pytest.approx(v["current"], rel=1e-9, abs=1e-5)


@given(hours, rate, discount, st.floats(1.0, 1.2))
def test_pure_rate_rise_is_all_rate(h, r, d, uplift):
    v = decompose([grade_row(h + 1, h + 1, r, r * uplift, d, d)])
    assert v["rate"] == pytest.approx(v["current"] - v["base"], abs=1e-4)
    assert abs(v["volume"]) + abs(v["mix"]) + abs(v["discount"]) < 1e-4


def test_pure_mix_shift_has_no_volume():
    v = decompose([grade_row(10, 5, 500, 500, 0, 0), grade_row(10, 15, 100, 100, 0, 0)])
    assert v["volume"] == 0
    assert v["mix"] == pytest.approx(-2000)
    assert v["rate"] == v["discount"] == 0


def test_new_grade_has_no_rate_effect():
    v = decompose([grade_row(10, 10, 200, 200, 0, 0), grade_row(0, 5, 100, 100, 0.2, 0.2)])
    assert v["rate"] == v["discount"] == 0
    assert v["volume"] + v["mix"] == pytest.approx(400)


def test_kpis_match_the_catalogue(firm):
    assert set(firm.kpis(FY26)) == set(CATALOGUE)


@pytest.mark.parametrize("parent", ["FIRM", "BUS", "DIS", "LIT"])
def test_children_add_up_to_their_parent(firm, parent):
    total = firm.kpis(FY26, parent)
    for key in ("hours", "net_value", "billed", "cash"):
        assert sum(c[key] for c in firm.children(FY26, parent)) == pytest.approx(total[key])


def test_leaf_unit_drills_to_itself(firm):
    assert [c["unit_id"] for c in firm.children(FY26, "PC")] == ["PC"]


def test_waterfall_reaches_cash(firm):
    steps = {s["step"]: s["amount"] for s in firm.waterfall(FY26)}
    assert steps["Standard value"] + steps["Agreed discounts"] + steps[
        "Billing write-downs"
    ] == pytest.approx(steps["Billed"], abs=0.02)
    assert steps["Billed"] + steps["Bad debt"] + steps["Still owed"] == pytest.approx(
        steps["Cash"], abs=0.02
    )


def test_waterfall_of_an_empty_month_is_zero(firm):
    november = Period(date(2024, 11, 1), date(2024, 11, 1))
    assert all(s["amount"] == 0 for s in firm.waterfall(november))


def test_restatement_bridge_is_complete(firm):
    steps = firm.restatement(APRIL, REPORTED, RESTATED)
    assert sum(s["amount"] for s in steps[:-1]) == pytest.approx(steps[-1]["amount"], abs=0.05)
    assert steps[0]["amount"] == pytest.approx(firm.recorded_as_of(APRIL, REPORTED), abs=0.01)
    assert steps[-1]["amount"] == pytest.approx(firm.recorded_as_of(APRIL, RESTATED), abs=0.01)


def test_past_reports_are_reproducible(firm):
    """What was known on a date never changes, however much is corrected later."""
    before = firm.recorded_as_of(APRIL, REPORTED)
    assert before != firm.recorded_as_of(APRIL, RESTATED)
    assert firm.recorded_as_of(APRIL, REPORTED) == before
    assert firm.recorded_as_of(APRIL, date(2026, 3, 31)) == 0


def test_transfers_net_across_units(firm, con):
    parts = [
        {s["step"]: s["amount"] for s in firm.restatement(APRIL, REPORTED, RESTATED, u)}
        for u in ("BUS", "DIS", "IND")
    ]
    whole = {s["step"]: s["amount"] for s in firm.restatement(APRIL, REPORTED, RESTATED)}
    for step in whole:
        assert sum(p[step] for p in parts) == pytest.approx(whole[step], abs=0.05)


def test_restatement_dates_must_be_ordered(firm):
    with pytest.raises(BadRequest):
        firm.restatement(APRIL, RESTATED, REPORTED)


def test_lockup_needs_three_months(firm):
    rows = firm.lockup_trend(FY25)
    assert [r["lockup_days"] is None for r in rows[:3]] == [True, True, False]
    assert rows[2]["lockup_days"] == pytest.approx(rows[2]["wip_days"] + rows[2]["debtor_days"])


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2026, 1, 2), date(2026, 2, 1)),
        (date(2026, 3, 1), date(2026, 2, 1)),
        (date(2020, 1, 1), date(2026, 2, 1)),
        (date(2026, 1, 1), date(2027, 2, 1)),
    ],
)
def test_bad_periods_are_rejected(start, end):
    with pytest.raises(BadRequest):
        Period(start, end)


def test_head_cannot_leave_their_unit(con):
    head = Metrics(con, USERS["head_disputes"])
    assert head.kpis(FY26) == Metrics(con, USERS["mp"]).kpis(FY26, "DIS")
    for unit in ("FIRM", "BUS", "EMP", "NOPE", "x' OR 1=1 --"):
        with pytest.raises(AccessDenied):
            head.kpis(FY26, unit)


def test_barred_matters_never_appear(con):
    walled = {r[0] for r in con.execute("SELECT DISTINCT matter_id FROM dim_wall").fetchall()}
    for user_id in ("head_disputes", "head_realestate", "head_construction"):
        metrics = Metrics(con, USERS[user_id])
        seen, page = set(), 1
        while items := metrics.matters(page=page, size=100)["items"]:
            seen |= {m["matter_id"] for m in items}
            page += 1
        assert seen and not seen & walled


def test_listed_user_sees_everything(firm):
    assert firm.matters()["restricted"]["matters"] == 0


def test_small_restricted_groups_hide_their_value(con):
    for user in USERS.values():
        restricted = Metrics(con, user).matters()["restricted"]
        assert (restricted["recorded"] is None) == (restricted["matters"] < 3)


def test_paging_covers_each_matter_once(firm):
    first = firm.matters(size=7)
    seen = []
    for page in range(1, first["total"] // 7 + 2):
        seen += [m["matter_id"] for m in firm.matters(page=page, size=7)["items"]]
    assert len(seen) == len(set(seen)) == first["total"]


@pytest.mark.parametrize("kwargs", [{"sort": "1; DROP TABLE x"}, {"page": 0}, {"size": 101}])
def test_matter_listing_validates_input(firm, kwargs):
    with pytest.raises(BadRequest):
        firm.matters(**kwargs)
