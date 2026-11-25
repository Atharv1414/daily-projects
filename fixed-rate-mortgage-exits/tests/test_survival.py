import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from mortgage_exits import survival

CAUSES = (1, 2, 3, 4)


def test_kaplan_meier_by_hand():
    # 5 at risk, 1 leaves; 3 at risk after one is lost, 1 leaves; 2 reach the end.
    s = survival.kaplan_meier([0] * 5, [1, 1, 2, 3, 3], [1, 0, 1, 0, 0], 3)
    assert s == pytest.approx([4 / 5, 4 / 5 * 2 / 3, 4 / 5 * 2 / 3])


def test_aalen_johansen_by_hand():
    aj = survival.aalen_johansen([0] * 4, [1, 2, 2, 2], [1, 2, 1, 0], 2, (1, 2))
    assert survival.cif_at(aj, 1, 2)["cif"] == pytest.approx(1 / 4 + 3 / 4 * 1 / 3)
    assert survival.cif_at(aj, 2, 2)["cif"] == pytest.approx(3 / 4 * 1 / 3)


def test_delayed_entry_joins_the_risk_set_late():
    n, _ = survival.risk_table([0, 0, 2], [3, 1, 3], [0, 1, 0], 3, (1,))
    assert n.tolist() == [2, 1, 2]


def test_without_censoring_incidence_is_a_simple_share():
    rng = np.random.default_rng(1)
    cause = rng.choice([1, 2, 3], 500)
    exit_ = rng.integers(1, 7, 500)
    aj = survival.aalen_johansen(np.zeros(500), exit_, cause, 6, (1, 2, 3))
    for k in (1, 2, 3):
        assert survival.cif_at(aj, k, 6)["cif"] == pytest.approx((cause == k).mean())


def test_variance_matches_the_binomial_without_censoring():
    rng = np.random.default_rng(2)
    cause = rng.choice([1, 2], 2000, p=[0.3, 0.7])
    aj = survival.aalen_johansen(np.zeros(2000), rng.integers(1, 6, 2000), cause, 5, (1, 2))
    p = (cause == 1).mean()
    assert survival.cif_at(aj, 1, 5)["se"] == pytest.approx(np.sqrt(p * (1 - p) / 2000), rel=0.03)


def test_intervals_cover_the_truth_about_95_percent_of_the_time():
    rng = np.random.default_rng(3)
    truth = sum(0.1 * 0.7 ** (t - 1) for t in range(1, 6))  # cause 1 at 0.1, cause 2 at 0.2 a month
    hits = 0
    for _ in range(300):
        u = rng.random((300, 5))
        event = np.where(u < 0.1, 1, np.where(u < 0.3, 2, 0))
        first = np.where(event.any(axis=1), (event > 0).argmax(axis=1), 5)
        lost = rng.integers(2, 8, 300)
        exit_ = np.minimum(np.minimum(first + 1, lost), 5)
        seen = (first + 1 <= lost) & (first < 5)
        cause = np.where(seen, event[np.arange(300), np.minimum(first, 4)], 0)
        row = survival.cif_at(survival.aalen_johansen(np.zeros(300), exit_, cause, 5, (1, 2)), 1, 5)
        hits += row["low"] <= truth <= row["high"]
    assert 0.91 <= hits / 300 <= 0.985


def test_ignoring_delayed_entry_is_biased_and_allowing_for_it_is_not():
    rng = np.random.default_rng(4)
    n = 60_000
    time = rng.geometric(0.15, n)
    entry = np.where(rng.random(n) < 0.5, rng.integers(1, 8, n), 0)
    seen = time > entry
    exit_, cause = np.minimum(time[seen], 12), (time[seen] <= 12).astype(int)
    truth = 1 - 0.85**6
    right = survival.aalen_johansen(entry[seen], exit_, cause, 12, (1,))
    wrong = survival.aalen_johansen(entry[seen] * 0, exit_, cause, 12, (1,))
    assert survival.cif_at(right, 1, 6)["cif"] == pytest.approx(truth, abs=0.01)
    assert survival.cif_at(wrong, 1, 6)["cif"] < truth - 0.05


@given(
    st.lists(
        st.tuples(st.integers(0, 4), st.integers(1, 8), st.integers(0, 4)), min_size=1, max_size=80
    )
)
def test_incidences_are_probabilities(rows):
    entry = [r[0] for r in rows]
    exit_ = [r[0] + r[1] for r in rows]
    cause = [r[2] for r in rows]
    aj = survival.aalen_johansen(entry, exit_, cause, 10)
    wide = aj.pivot(index="month", columns="cause", values="cif")
    assert (wide.diff().dropna() >= -1e-12).all().all()
    assert (wide.sum(axis=1) <= 1 + 1e-9).all()
    assert (aj["low"] <= aj["cif"] + 1e-9).all() and (aj["high"] >= aj["cif"] - 1e-9).all()


@pytest.mark.parametrize("k", CAUSES)
def test_naive_estimate_is_never_lower(data, k):
    args = data["entry"], data["exit"], data["cause"]
    aj = survival.aalen_johansen(*args, 24)
    naive = survival.naive_one_minus_km(*args, 24, k)
    assert (naive >= aj[aj["cause"] == k]["cif"].to_numpy() - 1e-12).all()


def test_rejects_no_time_at_risk():
    with pytest.raises(ValueError, match="at least one month"):
        survival.risk_table([2], [2], [1], 3, (1,))


def test_missing_estimate_is_an_error():
    with pytest.raises(KeyError):
        survival.cif_at(pd.DataFrame({"cause": [1], "month": [1]}), 2, 1)


def test_bootstrap_difference_is_zero_for_the_same_group(data):
    point, low, high = survival.bootstrap_difference(
        data, data["cause"] >= 0, data["cause"] >= 0, 2, 12, 30
    )
    assert point == 0 and low < 0 < high
    with pytest.raises(ValueError, match="empty"):
        survival.bootstrap_difference(data, data["cause"] > 9, data["cause"] >= 0, 2, 12, 5)
