from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fnol_business_case import analysis
from fnol_business_case.datagen import PILOT_REGIONS, GenConfig, generate_claims


def test_generator_is_seeded_and_messy():
    a = generate_claims(GenConfig(claims_per_month=200))
    b = generate_claims(GenConfig(claims_per_month=200))
    pd.testing.assert_frame_equal(a, b)
    assert a.days_to_settle.isna().any() and a.nps_score.isna().mean() > 0.7
    assert (a.fnol_handle_minutes > 180).any()
    assert set(a[a.channel == "Digital"].region) <= set(PILOT_REGIONS)


def test_cleaning_log_and_mis_keyed_handle_times(claims):
    assert claims.fnol_handle_minutes.max() <= analysis.MAX_HANDLE_MINUTES
    _, log = analysis.clean(generate_claims(GenConfig(claims_per_month=200)))
    steps = dict(log.steps)
    assert steps["rows received"] > 0
    assert any("mis-keyed" in s for s in steps)


@pytest.mark.parametrize(
    ("scores", "expected"),
    [([10, 10, 9, 0], 50.0), ([7, 8], 0.0), ([0, 1, 2], -100.0), ([np.nan, 10], 100.0)],
)
def test_nps(scores, expected):
    assert analysis.nps(pd.Series(scores, dtype=float)) == pytest.approx(expected)


def test_nps_empty_is_nan():
    assert np.isnan(analysis.nps(pd.Series([np.nan])))


def test_baseline_sensible(claims):
    b = analysis.baseline(claims)
    assert 0.8 < b["phone_share"] < 0.9
    assert 15 < b["mean_days_to_settle"] < 30
    assert 35 < b["rental_cost_per_day"] < 60


def test_digital_handle_time_lower_with_ci(claims):
    c = analysis.channel_comparison(claims)[0]
    assert c.metric == "FNOL handle minutes"
    assert c.ci_low < c.difference < c.ci_high < 0 and c.p_value < 0.001


def test_did_recovers_a_negative_effect_and_flat_pretrend(claims):
    d = analysis.difference_in_differences(claims, n_boot=200)
    assert d.ci_low <= d.estimate <= d.ci_high < 0
    assert d.per_digital_claim < d.estimate  # scaled up by take-up < 1
    assert 0.2 < d.digital_share_post < 0.6
    assert d.pre_trend_p > 0.05


def test_did_is_zero_when_there_is_no_effect(claims):
    fake = claims.copy()
    # Shuffle settlement times within each region: removes any treatment effect.
    rng = np.random.default_rng(0)
    fake["days_to_settle"] = fake.groupby("in_pilot_region").days_to_settle.transform(
        lambda s: s.sample(frac=1, random_state=int(rng.integers(1e6))).to_numpy()
    )
    d = analysis.difference_in_differences(fake, n_boot=200)
    assert d.ci_low < 0 < d.ci_high


def test_rental_slope_positive(claims):
    r = analysis.rental_vs_cycle(claims)
    assert 0.5 < r.slope_rental_days_per_cycle_day < 0.9 and r.r_squared > 0.5


def test_summary_tables(claims):
    t = analysis.summary_tables(claims)
    assert t["by_type"].claims.sum() > 0 and "Phone" in t["by_channel"].index
