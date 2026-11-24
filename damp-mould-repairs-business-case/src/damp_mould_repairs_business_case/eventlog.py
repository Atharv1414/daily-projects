"""Cleaning the extract, with a record of everything that was changed."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from .calendar import WorkingCalendar
from .datagen import ORIGIN
from .model import Activity

COLUMNS = ["case_id", "hazard", "activity", "started", "ended", "resource"]


class LogError(ValueError):
    """The extract cannot be used."""


def _key(text: str) -> str:
    return re.sub(r"[^a-z]+", " ", text.lower()).strip()


_NAMES = {_key(a.value): a.value for a in Activity} | {
    "survey": Activity.SURVEY.value,
    "no access": Activity.NO_ACCESS.value,
    "repair visit": Activity.REPAIR.value,
}
# When two events share a timestamp, this order breaks the tie.
_ORDER = {a.value: i for i, a in enumerate(Activity)}


@dataclass
class CleanLog:
    events: pd.DataFrame
    notes: list[tuple[str, int]] = field(default_factory=list)
    calendar: WorkingCalendar = field(default_factory=lambda: WorkingCalendar(ORIGIN))

    @property
    def cases(self) -> int:
        return int(self.events.case_id.nunique())


def clean(raw: pd.DataFrame) -> CleanLog:
    missing = set(COLUMNS) - set(raw.columns)
    if missing:
        raise LogError(f"missing columns: {sorted(missing)}")
    log = raw[COLUMNS].copy()
    notes: list[tuple[str, int]] = [("rows received", len(log))]

    test = ~log.case_id.astype(str).str.fullmatch(r"DM-\d{5}")
    notes.append(("rows from test or malformed cases removed", int(test.sum())))
    log = log[~test]

    tidy = log.activity.map(lambda a: _NAMES.get(_key(str(a))))
    if tidy.isna().any():
        raise LogError(f"unknown activities: {sorted(log.activity[tidy.isna()].unique())[:5]}")
    notes.append(("activity names standardised", int((tidy != log.activity).sum())))
    log["activity"] = tidy

    swapped = log.started > log.ended
    notes.append(("start and end swapped back", int(swapped.sum())))
    log.loc[swapped, ["started", "ended"]] = log.loc[swapped, ["ended", "started"]].to_numpy()

    copies = log.duplicated(["case_id", "activity", "ended", "resource"])
    notes.append(("exact duplicates removed", int(copies.sum())))
    log = log[~copies]
    # Durations stay unknown for these rows: filling them would invent service times.
    notes.append(
        ("missing start times (end time used for ordering)", int(log.started.isna().sum()))
    )

    log["order"] = log.activity.map(_ORDER)
    log["when"] = log.started.fillna(log.ended)
    log = log.sort_values(["case_id", "ended", "when", "order"], kind="stable")
    log = log.drop(columns=["order", "when"]).reset_index(drop=True)

    reported = log.groupby("case_id").activity.transform(lambda s: s.eq(Activity.REPORT).any())
    notes.append(("rows from cases without a report removed", int((~reported).sum())))
    log = log[reported].reset_index(drop=True)
    notes.append(("rows kept", len(log)))
    cleaned = CleanLog(log, notes)
    log["end_minute"] = [cleaned.calendar.to_minutes(t) for t in log.ended]
    log["start_minute"] = [
        float("nan") if pd.isna(t) else cleaned.calendar.to_minutes(t) for t in log.started
    ]
    return cleaned
