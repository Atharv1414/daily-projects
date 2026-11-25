import numpy as np
import pandas as pd
import pytest

from mortgage_exits import evaluation, hazards, survival, value
from mortgage_exits.config import LEFT, Economics
from mortgage_exits.datagen import TRUE_EFFECTS


@pytest.fixture(scope="module")
def panel(data, rates, study):
    return hazards.person_months(data, rates, study)


@pytest.fixture(scope="module")
def models(panel):
    return hazards.fit(panel, hazards.EXPLAIN)


def test_one_row_for_each_month_at_risk(data, panel):
    assert len(panel) == (data["exit"] - data["entry"]).sum()
    assert (panel["y"] > 0).sum() == (data["cause"] > 0).sum()
    assert panel.groupby("account_id")["month"].is_monotonic_increasing.all()


def test_incentive_appears_when_the_fix_ends(panel, study):
    after = panel[panel["month"] > study.lead_months]["incentive"]
    assert after.to_numpy() == pytest.approx(2.6)


@pytest.mark.parametrize("feature", hazards.EXPLAIN)
@pytest.mark.parametrize("cause", [1, 2])
def test_true_effects_are_recovered(models, cause, feature):
    row = models.hazard_ratios().set_index(["cause", "feature"]).loc[(cause, feature)]
    assert abs(row["log_hr"] - TRUE_EFFECTS[cause][feature]) < 4 * row["se"] + 0.02


def test_average_forecast_matches_the_observed_curve(data, panel):
    models = hazards.fit(panel, hazards.BASELINE)
    whole = data[data["entry"] == 0]
    aj = survival.aalen_johansen(data["entry"], data["exit"], data["cause"], 12)
    got = models.cif(whole, 12)[LEFT - 1, :, 11].mean()
    assert got == pytest.approx(survival.cif_at(aj, LEFT, 12)["cif"], abs=0.02)


def test_forecasts_are_probabilities(data, models):
    cif = models.cif(data.head(300).assign(incentive=4.0, shock=2.0), 24)
    assert (np.diff(cif, axis=2) >= -1e-12).all()
    assert cif[:, :, -1].sum(axis=0).max() <= 1 + 1e-9


def test_too_few_events_is_an_error(panel):
    with pytest.raises(hazards.ModelError, match="too few"):
        hazards.fit(panel.head(200), hazards.BASELINE)


def test_missing_feature_values_are_an_error(panel):
    broken = panel.assign(shock=np.nan)
    with pytest.raises(hazards.ModelError, match="missing"):
        hazards.fit(broken, hazards.BASELINE)


def test_training_data_stops_at_the_split(data, study):
    train, test = evaluation.temporal_split(data, study)
    last = train["start"].dt.year * 12 + train["start"].dt.month + train["exit"] - 1
    assert (last < study.split.year * 12 + study.split.month).all()
    assert (test["start"] >= study.split).all()
    assert not set(train["account_id"]) & set(test["account_id"])


def test_events_after_the_split_cannot_leak_into_training(data, study, rates):
    train, _ = evaluation.temporal_split(data, study)
    changed = data.copy()
    after = changed["event_date"] >= study.split
    changed.loc[after, "cause"] = 4
    again, _ = evaluation.temporal_split(changed, study)
    pd.testing.assert_frame_equal(train[["exit", "cause"]], again[["exit", "cause"]])


def test_weights_undo_censoring():
    rng = np.random.default_rng(5)
    n = 60_000
    time, lost = rng.geometric(0.08, n), rng.integers(3, 30, n)
    frame = pd.DataFrame(
        {
            "entry": 0,
            "exit": np.minimum(time, lost),
            "cause": np.where(time <= lost, np.where(rng.random(n) < 0.6, 2, 1), 0),
        }
    )
    y, w = evaluation.ipcw(frame, 12)
    assert np.average(y, weights=w) == pytest.approx(0.6 * (1 - 0.92**12), abs=0.01)
    assert w.sum() == pytest.approx(n, rel=0.01)


def test_auc_by_hand_and_with_ties():
    one = np.ones(4)
    y = np.array([0, 0, 1, 1.0])
    assert evaluation.auc(y, np.array([0.1, 0.4, 0.35, 0.8]), one) == pytest.approx(0.75)
    assert evaluation.auc(y, np.full(4, 0.5), one) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        evaluation.auc(np.zeros(4), np.arange(4.0), one)


def test_backtest_beats_the_flat_rate(results):
    s = results.test.scores.set_index("model")["brier"]
    assert s["Competing-risks model"] < s["Same rate for everyone"]
    gap = results.test.differences.set_index("versus").loc["Same rate for everyone"]
    assert gap["low"] > 0


def test_calibration_bins_hold_everyone(results):
    part = results.test.calibration
    for _, group in part.groupby("model"):
        assert group["accounts"].sum() == results.test.test_rows
        assert group["predicted"].is_monotonic_increasing


@pytest.fixture
def few():
    return pd.DataFrame(
        {"p": [0.5, 0.5, 0.01], "balance": [300_000, 100_000, 50_000], "y": [1, 0, 0], "w": 1.0}
    )


def test_plan_puts_the_biggest_expected_loss_first(few):
    got = value.plan(few, Economics(0.01, 2, 22, 0.1))
    assert got["balance"].tolist() == [300_000, 100_000, 50_000]
    assert got["expected"].tolist() == pytest.approx([278, 78, -21])


def test_gains_start_at_nothing_and_end_at_everything(results):
    for _, part in results.gains.groupby("ranking"):
        assert part["reached"].iloc[0] == 0
        assert part["reached"].iloc[-1] == pytest.approx(1)
        assert part["reached"].is_monotonic_increasing


def test_break_even_is_where_a_call_nets_nothing(results):
    rate = results.tenths["break_even_save_rate"]
    net = results.tenths["margin_lost"] * rate - Economics().call_cost
    assert net.to_numpy() == pytest.approx(0, abs=1e-9)


def test_planned_calls_grow_with_the_save_rate(results):
    assert results.sensitivity["calls"].is_monotonic_increasing
