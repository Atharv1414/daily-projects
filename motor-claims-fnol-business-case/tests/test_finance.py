from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from fnol_business_case import finance

BASE = {
    "annual_claims": 31_000,
    "phone_share": 0.86,
    "rental_share": 0.39,
    "rental_cost_per_day": 46.0,
    "mean_indemnity": 3_270,
    "fraud_referral_rate": 0.02,
}


@pytest.fixture
def A():
    return finance.from_evidence(BASE, (-4.4, -6.4, -2.7), (-18.1, -18.8, -17.4), 0.7)


def test_npv_irr_known_values():
    flows = np.array([-1000.0, 500, 500, 500])
    assert finance.npv(0.1, flows) == pytest.approx(243.43, abs=0.01)
    assert finance.irr(flows) == pytest.approx(0.2338, abs=1e-4)
    assert finance.npv(finance.irr(flows), flows) == pytest.approx(0, abs=1e-4)


def test_irr_nan_without_sign_change():
    assert np.isnan(finance.irr(np.array([-100.0, -10, -10])))


@pytest.mark.parametrize(
    ("flows", "expected"),
    [([-100, 50, 50], 2.0), ([-100, 40, 40, 40], 2.5), ([-100, 10], float("inf")), ([10, 10], 0.0)],
)
def test_payback(flows, expected):
    assert finance.payback_years(np.array(flows, dtype=float)) == pytest.approx(expected)


def test_discounted_payback_is_later(A):
    m = finance.evaluate(finance.values(A))
    assert m.discounted_payback > m.payback


@given(st.floats(0.0, 0.3), st.floats(-200, 200), st.floats(-200, 200))
def test_npv_linear_in_flows(rate, a, b):
    f1, f2 = np.array([a, b, 1.0]), np.array([b, a, 2.0])
    assert finance.npv(rate, f1 + f2) == pytest.approx(
        finance.npv(rate, f1) + finance.npv(rate, f2), abs=1e-6
    )


def test_cash_flow_lines_add_up(A):
    lines = finance.cash_flows(finance.values(A))
    np.testing.assert_allclose(lines["net"], lines["benefits"] + lines["costs"])
    assert lines["capex"][0] < 0 and lines["benefits"][0] == 0
    assert np.all(np.diff(lines["benefits"][1:4]) > 0)  # adoption ramp


def test_vectorised_matches_scalar(A):
    v = finance.values(A)
    vec = {k: np.full(3, x) for k, x in v.items()}
    scalar_net = finance.cash_flows(v)["net"]
    np.testing.assert_allclose(finance.cash_flows(vec)["net"], np.tile(scalar_net, (3, 1)))


def test_more_adoption_never_lowers_npv(A):
    v = finance.values(A)
    npvs = [finance.evaluate({**v, "target_adoption": a}).npv for a in np.linspace(0, 1, 11)]
    assert all(b >= a for a, b in zip(npvs, npvs[1:], strict=False))


def test_scenarios_ordered(A):
    s = finance.scenarios(A)
    assert s.loc["Pessimistic", "NPV"] < s.loc["Base", "NPV"] < s.loc["Optimistic", "NPV"]


def test_tornado_sorted_and_brackets_base(A):
    t = finance.tornado(A)
    assert list(t.swing) == sorted(t.swing, reverse=True)
    for row in t.itertuples():
        assert min(row.npv_low, row.npv_high) <= row.base_npv + 1e-6
        assert max(row.npv_low, row.npv_high) >= row.base_npv - 1e-6


def test_monte_carlo_reproducible_and_consistent(A):
    a, b = finance.monte_carlo(A, n=2_000, seed=1), finance.monte_carlo(A, n=2_000, seed=1)
    assert a.p50 == b.p50 and a.p10 < a.p50 < a.p90 and 0 <= a.p_positive <= 1


def test_break_even_gives_zero_npv(A):
    x = finance.break_even(A, "target_adoption", 0.01, 0.95)
    v = finance.values(A)
    assert finance.evaluate({**v, "target_adoption": x}).npv == pytest.approx(0, abs=50)


def test_assumption_range_validated():
    with pytest.raises(ValueError):
        finance.Assumption("x", "x", base=5, low=6, high=7, unit="", source="")


def test_with_override_widens_range(A):
    B = finance.with_override(A, target_adoption=0.9)
    assert B["target_adoption"].high == 0.9 and A["target_adoption"].base == 0.55
