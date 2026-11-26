"""The 2025/26 academic year: terms, half-terms, bank holidays, INSET days and census dates.

Attendance only counts on days a school is open to pupils, so the calendar is the first
dimension the mart needs. A typical English school is open 190 days a year; five further
INSET (training) days are taken out of term time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

ACADEMIC_YEAR = "2025/26"


@dataclass(frozen=True)
class Term:
    name: str
    start: date
    end: date
    half_term: tuple[date, date]
    census: date  # school census day: pupil characteristics are taken as at this date


TERMS: tuple[Term, ...] = (
    Term(
        "Autumn",
        date(2025, 9, 1),
        date(2025, 12, 19),
        (date(2025, 10, 27), date(2025, 10, 31)),
        date(2025, 10, 2),
    ),
    Term(
        "Spring",
        date(2026, 1, 5),
        date(2026, 3, 27),
        (date(2026, 2, 16), date(2026, 2, 20)),
        date(2026, 1, 15),
    ),
    Term(
        "Summer",
        date(2026, 4, 13),
        date(2026, 7, 20),
        (date(2026, 5, 25), date(2026, 5, 29)),
        date(2026, 5, 21),
    ),
)

BANK_HOLIDAYS = frozenset({date(2026, 5, 4)})  # early May; the others fall in holidays
INSET_DAYS = frozenset(
    {date(2025, 9, 1), date(2025, 9, 2), date(2026, 1, 5), date(2026, 4, 13), date(2026, 7, 20)}
)


@dataclass(frozen=True)
class SchoolDay:
    day: date
    term: str
    week_start: date  # Monday
    week_of_year: int  # school week number, 1 = first teaching week


def _weekdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def school_days() -> list[SchoolDay]:
    """Every day the schools are open to pupils, in order."""
    days: list[SchoolDay] = []
    weeks: dict[date, int] = {}
    for term in TERMS:
        for d in _weekdays(term.start, term.end):
            if term.half_term[0] <= d <= term.half_term[1]:
                continue
            if d in BANK_HOLIDAYS or d in INSET_DAYS:
                continue
            monday = d - timedelta(days=d.weekday())
            weeks.setdefault(monday, len(weeks) + 1)
            days.append(SchoolDay(d, term.name, monday, weeks[monday]))
    return days


def term_of(day: date) -> Term | None:
    for term in TERMS:
        if term.start <= day <= term.end:
            return term
    return None
