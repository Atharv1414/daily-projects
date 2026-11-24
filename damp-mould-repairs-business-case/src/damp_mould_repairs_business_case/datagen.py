"""The case-management extract: a year of as-is operation, exported badly.

The process parameters used here are deliberately not the model defaults. The analysis must
recover them from the log, as it would with a real extract.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .calendar import WorkingCalendar
from .model import Activity, Parameters
from .simulation import simulate

ORIGIN = date(2025, 9, 1)
TRUE_PARAMETERS = Parameters(
    arrivals_per_day=24.0,
    survey_minutes=88.0,
    no_access_rate=0.19,
    repair_minutes=240.0,
    repeat_repair_rate=0.21,
    parts_days=7.5,
)
ALIASES = {
    Activity.SURVEY: ["survey visit", "Survey Visit ", "SURVEY"],
    Activity.NO_ACCESS: ["No access", "survey - no access"],
    Activity.REPAIR: ["repair", "Repair visit"],
    Activity.MAKE_SAFE: ["Make-safe", "make safe"],
}


def event_log(seed: int = 2026) -> pd.DataFrame:
    """One row per completed activity, with realistic export faults."""
    calendar = WorkingCalendar(ORIGIN)
    result = simulate(TRUE_PARAMETERS, seed)
    first = {c.case_id for c in result.measured}
    rows = [
        (
            f"DM-{e.case_id:05d}",
            e.hazard.value,
            e.activity.value,
            calendar.to_datetime(e.start),
            calendar.to_datetime(e.end),
            e.resource,
        )
        for e in result.events
        if e.case_id in first
    ]
    log = pd.DataFrame(
        rows, columns=["case_id", "hazard", "activity", "started", "ended", "resource"]
    )
    return _add_faults(log, np.random.default_rng(seed + 1))


def _add_faults(log: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    log = log.copy()
    for activity, names in ALIASES.items():
        rows = np.flatnonzero((log.activity == activity.value) & (rng.random(len(log)) < 0.12))
        log.loc[rows, "activity"] = rng.choice(names, len(rows))
    # Crews forget to tap "start", so the start is missing.
    visits = log.resource.str.startswith(("crew", "surveyor")).to_numpy()
    log.loc[visits & (rng.random(len(log)) < 0.04), "started"] = pd.NaT
    # Start and end swapped on paper forms.
    swap = np.flatnonzero(visits & (rng.random(len(log)) < 0.006) & log.started.notna())
    started = log.loc[swap, "started"].to_numpy().copy()
    log.loc[swap, "started"] = log.loc[swap, "ended"].to_numpy()
    log.loc[swap, "ended"] = started
    # Some cases never had triage recorded, and some inspections were skipped.
    triage = (log.activity == Activity.TRIAGE.value) & (rng.random(len(log)) < 0.015)
    skipped = (log.activity == Activity.INSPECT.value) & (rng.random(len(log)) < 0.05)
    log = log[~(triage | skipped)]
    duplicates = log.sample(frac=0.012, random_state=int(rng.integers(1 << 31)))
    test_cases = log.head(6).assign(case_id="TEST-1")
    log = pd.concat([log, duplicates, test_cases])
    return log.sample(frac=1, random_state=int(rng.integers(1 << 31))).reset_index(drop=True)
