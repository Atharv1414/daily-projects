import numpy as np
import pandas as pd
import pytest

from outpatient_dna import impact
from outpatient_dna.forecasting import MODELS, BookingIndex, backtest, weekly_series
from outpatient_dna.modelling import auc, fit
from outpatient_dna.stats import two_proportion_test


@pytest.mark.parametrize(
    "scores,expected",
    [
        ([0.1, 0.2, 0.8, 0.9], 1.0),
        ([0.9, 0.8, 0.2, 0.1], 0.0),
        ([0.5, 0.5, 0.5, 0.5], 0.5),
    ],
)
def test_auc_known_values(scores, expected):
    assert auc(np.array([0, 0, 1, 1]), np.array(scores)) == pytest.approx(expected)


def test_auc_requires_both_classes():
    with pytest.raises(ValueError):
        auc(np.array([1, 1]), np.array([0.2, 0.3]))


@pytest.fixture(scope="module")
def model(dataset):
    return fit(dataset.attendable)


def test_model_recovers_known_directions(model):
    ors = model.odds_ratios.set_index("term")["odds_ratio"]
    assert ors["age: 18-29"] > 1.3
    assert ors["mode: Telephone"] < 0.85
    assert ors["IMD decile (per step up, 1 = most deprived)"] < 1
    assert 0.58 < model.auc_test < 0.75


def test_calibration_deciles(model):
    c = model.calibration
    assert list(c["decile"]) == list(range(1, 11))
    assert c["observed"].iloc[-1] > 2 * c["observed"].iloc[0]


def test_weekly_series_drops_partial_weeks(dataset):
    w = weekly_series(dataset.appointments)
    assert w.index.min() > dataset.appointments["week"].min()
    assert ((w["dna_rate"] > 0) & (w["dna_rate"] < 0.3)).all()


def test_booking_index_counts():
    a = pd.DataFrame(
        {
            "week": pd.to_datetime(["2025-01-06"] * 3),
            "booked_date": pd.to_datetime(["2024-12-01", "2024-12-20", "2025-01-02"]),
        }
    )
    idx = BookingIndex(a)
    assert idx.booked_by(pd.Timestamp("2025-01-06"), pd.Timestamp("2024-12-20")) == 2
    assert idx.booked_by(pd.Timestamp("2025-02-03"), pd.Timestamp("2025-01-01")) == 0


def test_backtest_shape_and_no_lookahead(dataset):
    bt = backtest(dataset.appointments, horizon=2, n_origins=5)
    assert set(bt.summary["model"]) == set(MODELS)
    assert (bt.errors["abs_error"] >= 0).all()
    series = weekly_series(dataset.appointments)
    naive = bt.errors[(bt.errors["model"] == "naive") & (bt.errors["horizon"] == 2)]
    for origin, forecast in zip(naive["origin"], naive["forecast"], strict=True):
        assert forecast == series.loc[origin, "dnas"]  # only data up to the origin
    assert bt.best_model in MODELS


def test_impact_scenarios(dataset, model):
    trial = two_proportion_test(100, 1000, 80, 1000)
    sms = impact.sms_rollout(dataset.attendable, trial, 2025)
    assert sms.intervention_cost_gbp == 0 and sms.roi == float("inf")
    assert sms.dnas_avoided_low < sms.dnas_avoided < sms.dnas_avoided_high
    calls = impact.targeted_calls(model.test_scored, 100_000)
    assert calls.appointments_targeted == pytest.approx(10_000, rel=0.02)
    assert calls.net_saving_gbp == pytest.approx(
        calls.dnas_avoided * 160 - calls.intervention_cost_gbp
    )
