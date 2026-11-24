from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from damp_mould_repairs_business_case import datagen, eventlog, mining
from damp_mould_repairs_business_case.calendar import DAY_MINUTES, WorkingCalendar, is_working_day
from damp_mould_repairs_business_case.model import CLOCK, Activity, CaseRecord, Hazard, Parameters


@pytest.fixture(scope="module")
def raw():
    return datagen.event_log()


@pytest.fixture(scope="module")
def log(raw):
    return eventlog.clean(raw)


CALENDAR = WorkingCalendar(date(2025, 9, 1))


@pytest.mark.parametrize(
    ("day", "expected"),
    [("2025-12-24", True), ("2025-12-25", False), ("2025-12-27", False), ("2026-04-03", False),
     ("2026-04-07", True)],
)  # fmt: skip
def test_working_days(day, expected):
    assert is_working_day(date.fromisoformat(day)) is expected


@given(st.floats(0, 400 * DAY_MINUTES - 1))
def test_calendar_round_trip(minute):
    assert CALENDAR.to_minutes(CALENDAR.to_datetime(minute)) == pytest.approx(minute, abs=0.02)


def test_out_of_hours_moves_to_the_next_opening():
    friday_night = CALENDAR.to_minutes(datetime(2025, 9, 5, 22, 0))
    sunday = CALENDAR.to_minutes(datetime(2025, 9, 7, 12, 0))
    monday = CALENDAR.to_minutes(datetime(2025, 9, 8, 9, 0))
    assert friday_night == sunday == monday


def test_calendar_rejects_dates_past_its_end():
    with pytest.raises(ValueError, match="outside"):
        CALENDAR.to_minutes(datetime(2040, 1, 2))


def test_extract_is_deterministic(raw):
    pd.testing.assert_frame_equal(raw, datagen.event_log())


def test_cleaning_accounts_for_every_row(log):
    notes = dict(log.notes)
    removed = sum(n for k, n in notes.items() if "removed" in k)
    assert notes["rows received"] - removed == notes["rows kept"] == len(log.events)
    assert all(n > 0 for k, n in notes.items() if "without a report" not in k)


def test_cleaned_values_are_consistent(log):
    assert set(log.events.activity) <= {a.value for a in Activity}
    known = log.events.dropna(subset=["started"])
    assert (known.started <= known.ended).all()
    assert not log.events.case_id.str.startswith("TEST").any()


def test_missing_starts_are_not_invented(log):
    assert log.events.start_minute.isna().sum() == log.events.started.isna().sum() > 0


def test_cleaning_is_idempotent(log):
    again = eventlog.clean(log.events[eventlog.COLUMNS])
    pd.testing.assert_frame_equal(again.events, log.events)


def test_bad_extracts_are_refused(raw):
    with pytest.raises(eventlog.LogError, match="missing columns"):
        eventlog.clean(raw.drop(columns="hazard"))
    with pytest.raises(eventlog.LogError, match="unknown activities"):
        eventlog.clean(raw.assign(activity="Teleport"))


def small_log(*rows):
    """rows: (case, hazard, activity, start hour, end hour) on one day."""
    frame = pd.DataFrame(
        [(f"DM-{c:05d}", h, a, datetime(2025, 11, 3, s), datetime(2025, 11, 3, e), "x")
         for c, h, a, s, e in rows],
        columns=eventlog.COLUMNS,
    )  # fmt: skip
    return eventlog.clean(frame)


HAPPY = [
    (1, "routine", "Report received", 9, 9), (1, "routine", "Triage", 9, 10),
    (1, "routine", "Survey visit", 10, 11), (1, "routine", "Repair", 13, 15),
    (1, "routine", "Post inspection", 15, 16), (1, "routine", "Case closed", 16, 16),
]  # fmt: skip


def test_conforming_case_has_perfect_fitness():
    result = mining.check_conformance(small_log(*HAPPY))
    assert (result.fitness, result.conforming_cases, result.violations) == (1.0, 1.0, [])


def test_skipped_inspection_is_found():
    result = mining.check_conformance(small_log(*HAPPY[:4], HAPPY[5]))
    assert result.violations == [("Repair → Case closed", 1)]
    assert result.conforming_cases == 0


def test_missing_summary_is_found_only_where_required():
    significant = [(1, "significant", *r[2:]) for r in HAPPY]
    result = mining.check_conformance(small_log(*significant))
    assert result.violations == [("closed without a written summary", 1)]


def test_open_case_is_not_penalised_for_being_open():
    assert mining.check_conformance(small_log(*HAPPY[:3])).fitness == 1.0


def test_directly_follows_measures_waiting():
    edges = {(e.source, e.target): e for e in mining.directly_follows(small_log(*HAPPY))}
    assert edges["Survey visit", "Repair"].median_wait_days == pytest.approx(2 / 8)


def test_variants_cover_all_cases(log):
    every = mining.variants(log, top=10_000)
    assert sum(n for _, n, _ in every) == log.cases
    assert sum(s for _, _, s in every) == pytest.approx(1)


def test_injected_departures_are_detected(log):
    found = dict(mining.check_conformance(log).violations)
    assert found["Repair → Case closed"] > 100
    assert any(v.startswith("Report received → ") for v in found)


def test_waiting_dwarfs_working(log):
    table = mining.time_breakdown(log)
    assert table.wait.sum() > 5 * table.work.sum()


@pytest.mark.parametrize(
    ("name", "tolerance"),
    [("arrivals_per_day", 0.05), ("survey_minutes", 0.03), ("repair_minutes", 0.03),
     ("no_access_rate", 0.10), ("parts_rate", 0.05), ("parts_days", 0.10),
     ("repeat_repair_rate", 0.10), ("summary_minutes", 0.03), ("rebook_days", 0.10)],
)  # fmt: skip
def test_calibration_recovers_the_hidden_process(log, name, tolerance):
    estimated = mining.estimate_parameters(log, Parameters())
    truth = getattr(datagen.TRUE_PARAMETERS, name)
    assert getattr(estimated, name) == pytest.approx(truth, rel=tolerance)


def case(**values):
    return CaseRecord(1, values.pop("hazard", Hazard.SIGNIFICANT), 0.0, **values)


DAY = DAY_MINUTES


@pytest.mark.parametrize(
    ("record", "clock", "now", "expected"),
    [
        (case(investigated=10 * DAY), "investigate", 99 * DAY, True),
        (case(investigated=10 * DAY + 1), "investigate", 99 * DAY, False),
        (case(), "investigate", 5 * DAY, None),  # still within its limit
        (case(), "investigate", 11 * DAY, False),  # open and already late
        (case(), "summary", 99 * DAY, None),  # clock has not started
        (case(hazard=Hazard.ROUTINE, investigated=50 * DAY), "investigate", 99 * DAY, None),
        (case(hazard=Hazard.EMERGENCY, made_safe=2 * DAY), "emergency", 99 * DAY, False),
        (case(investigated=DAY, made_safe=6 * DAY), "make_safe", 99 * DAY, True),
    ],
)
def test_clock_outcomes(record, clock, now, expected):
    assert record.outcome(CLOCK[clock], now) is expected


def test_outcomes_are_plain_bools_even_with_numpy_times():
    """`is False` on a numpy bool is never true, which once hid every breach."""
    record = case(investigated=np.float64(11 * DAY))
    assert record.outcome(CLOCK["investigate"], np.float64(99 * DAY)) is False
