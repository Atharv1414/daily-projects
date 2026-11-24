from __future__ import annotations

import math

import pytest

from damp_mould_repairs_business_case.model import DAY_MINUTES, Activity, Hazard, Parameters
from damp_mould_repairs_business_case.simulation import (
    Estimate,
    Simulation,
    draw_cases,
    paired_difference,
    replicate,
    scenarios,
    simulate,
    summarise,
)


@pytest.fixture(scope="module")
def base():
    return simulate(Parameters(), seed=5)


def test_same_seed_same_result(base):
    again = simulate(Parameters(), seed=5)
    assert summarise(again) == summarise(base)


def test_scenarios_see_identical_cases():
    runs = [simulate(p, seed=3, horizon_days=60) for p in scenarios(Parameters()).values()]
    arrivals = [[(c.reported, c.hazard) for c in r.cases] for r in runs]
    assert all(a == arrivals[0] for a in arrivals)


def test_arrival_volume_and_mix_match_parameters():
    p = Parameters(seasonal_swing=0.0)
    draws = draw_cases(p, 2000, seed=1)
    assert len(draws) / 2000 == pytest.approx(p.arrivals_per_day, rel=0.02)
    emergencies = sum(d.hazard < p.hazard_mix[0] for d in draws) / len(draws)
    assert emergencies == pytest.approx(p.hazard_mix[0], abs=0.005)


def test_winter_is_busier_than_summer():
    draws = draw_cases(Parameters(), 253, seed=2)
    winter = sum(70 <= d.arrival / DAY_MINUTES < 115 for d in draws)
    summer = sum(195 <= d.arrival / DAY_MINUTES < 240 for d in draws)
    assert winter > 1.3 * summer


def test_nobody_works_on_two_things_at_once(base):
    by_person: dict[str, list[tuple[float, float]]] = {}
    for e in base.events:
        if e.resource.startswith(("crew", "surveyor", "admin", "triage")):
            by_person.setdefault(e.resource, []).append((e.start, e.end))
    for spans in by_person.values():
        spans.sort()
        assert all(a[1] <= b[0] + 1e-6 for a, b in zip(spans, spans[1:], strict=False))
    assert len([p for p in by_person if p.startswith("crew")]) == Parameters().crews


def test_cases_progress_in_order(base):
    for c in base.cases:
        if c.closed is None:
            continue
        assert c.reported <= c.investigated <= c.closed
        assert c.repair_started < c.closed
        if c.hazard is Hazard.SIGNIFICANT:
            assert c.investigated < c.made_safe <= c.repair_started
        if c.hazard is Hazard.EMERGENCY:
            assert c.made_safe < c.investigated


def test_events_and_cases_agree(base):
    closed = sum(e.activity is Activity.CLOSE for e in base.events)
    assert closed == sum(c.closed is not None for c in base.cases)


def test_quiet_queue_matches_theory():
    """M/G/1: mean wait = λE[S²] / 2(1-ρ), the Pollaczek-Khinchine formula."""
    p = Parameters(arrivals_per_day=12.0, seasonal_swing=0.0, triage_officers=1,
                   hazard_mix=(0.0, 0.0, 1.0), surveyors=60, crews=60)  # fmt: skip
    result = Simulation(p, draw_cases(p, 4000, seed=9), 4000).run(0)
    waits = [e.start - c.reported for e, c in _triage_pairs(result)]
    rate, mean = 12 / DAY_MINUTES, p.triage_minutes
    second_moment = mean**2 * math.exp(0.125)
    expected = rate * second_moment / (2 * (1 - rate * mean))
    assert sum(waits) / len(waits) == pytest.approx(expected, rel=0.06)


def _triage_pairs(result):
    cases = {c.case_id: c for c in result.cases}
    return [(e, cases[e.case_id]) for e in result.events if e.activity is Activity.TRIAGE]


def test_no_access_stops_after_three_attempts():
    result = simulate(Parameters(no_access_rate=1.0, surveyors=40), seed=1, horizon_days=80)
    attempts = [c.visits.get(Activity.NO_ACCESS, 0) for c in result.cases if c.investigated]
    assert attempts and set(attempts) == {3}


def test_perfect_process_has_no_rework():
    p = Parameters(no_access_rate=0, parts_rate=0, repeat_repair_rate=0, inspect_rate=0,
                   surveyors=60, crews=90, admin_officers=9, triage_officers=9)  # fmt: skip
    result = simulate(p, seed=1, horizon_days=80)
    assert Activity.NO_ACCESS not in result.counts and Activity.INSPECT not in result.counts
    assert summarise(result)["compliant_share"] == 1.0


def test_deadline_queue_rescues_make_safe_without_extra_staff():
    fifo = summarise(simulate(Parameters(), seed=11))
    edf = summarise(simulate(Parameters(deadline_queue=True), seed=11))
    assert edf["met_make_safe"] > fifo["met_make_safe"] + 0.1
    assert edf["use_crew"] == pytest.approx(fifo["use_crew"], abs=0.02)


def test_emergencies_jump_the_queue(base):
    assert summarise(base)["met_emergency"] > 0.99


def test_breach_count_matches_case_by_case(base):
    from damp_mould_repairs_business_case.model import CLOCKS

    breached = sum(any(c.outcome(k, base.horizon) is False for k in CLOCKS) for c in base.measured)
    assert summarise(base)["breached_cases"] == breached > 0


def test_pairing_narrows_the_interval():
    options = scenarios(Parameters())
    runs = {n: replicate(options[n], range(6)) for n in ("A. Do nothing", "B. Deadline queue only")}
    a, b = (r["mean_days"] for r in runs.values())
    paired = paired_difference(a, b)
    assert paired.high - paired.low < Estimate.of(a).high - Estimate.of(a).low


@pytest.mark.parametrize(
    "changes",
    [{"hazard_mix": (0.5, 0.5, 0.5)}, {"no_access_rate": 1.2}, {"crews": 0}, {"desk_rate": -0.1}],
)
def test_impossible_parameters_are_rejected(changes):
    with pytest.raises(ValueError):
        Parameters().change(**changes)


def test_estimate_interval():
    e = Estimate.of([1.0, 2.0, 3.0])
    assert e.mean == 2 and e.low < 2 < e.high
    assert Estimate.of([4.0]) == Estimate(4, 4, 4)
