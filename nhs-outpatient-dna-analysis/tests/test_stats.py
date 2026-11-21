import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from statsmodels.stats.proportion import proportion_confint, proportions_ztest

from outpatient_dna.stats import (
    chi_square,
    power_two_proportions,
    required_n_per_arm,
    srm_check,
    two_proportion_test,
    wilson_ci,
)


@pytest.mark.parametrize("x,n", [(0, 10), (3, 10), (80, 1000), (1000, 1000), (7, 23)])
def test_wilson_matches_statsmodels(x, n):
    lo, hi = wilson_ci(x, n)
    ref = proportion_confint(x, n, method="wilson")
    assert lo == pytest.approx(ref[0], abs=1e-9) and hi == pytest.approx(ref[1], abs=1e-9)


@pytest.mark.parametrize("x,n", [(1, 0), (-1, 10), (11, 10)])
def test_wilson_rejects_bad_input(x, n):
    with pytest.raises(ValueError):
        wilson_ci(x, n)


def test_two_proportion_matches_statsmodels_z():
    r = two_proportion_test(2023, 24984, 1662, 25216)
    z, p = proportions_ztest([1662, 2023], [25216, 24984])
    assert r.z == pytest.approx(z) and r.p_value == pytest.approx(p)
    assert r.diff_ci[0] < r.diff < r.diff_ci[1] < 0
    assert r.rr_ci[0] < r.relative_risk < r.rr_ci[1] < 1
    assert r.nnt == pytest.approx(1 / -r.diff)


def test_no_benefit_gives_infinite_nnt():
    r = two_proportion_test(50, 1000, 60, 1000)
    assert math.isinf(r.nnt) and not r.significant


def test_srm_detects_broken_randomisation():
    assert srm_check(5000, 5050) > 0.05
    assert srm_check(6000, 4000) < 1e-6


def test_required_n_gives_80_percent_power():
    n = required_n_per_arm(0.081, 0.066)
    assert power_two_proportions(0.081, 0.066, n) == pytest.approx(0.8, abs=0.01)


@given(st.integers(min_value=100, max_value=20_000))
def test_power_increases_with_sample_size(n):
    assert power_two_proportions(0.08, 0.065, n + 500) >= power_two_proportions(0.08, 0.065, n)


@given(st.integers(0, 500), st.integers(0, 500), st.integers(1, 500), st.integers(1, 500))
def test_chi_square_effect_size_bounded(a, b, c, d):
    table = np.array([[a + 1, c], [b + 1, d]])
    v = chi_square(table).cramers_v
    assert 0 <= v <= 1 + 1e-9
