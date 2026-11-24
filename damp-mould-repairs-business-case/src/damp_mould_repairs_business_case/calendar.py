"""Working time: the statutory clocks count working days, and the simulation runs on them."""

from __future__ import annotations

from bisect import bisect_left
from datetime import date, datetime, timedelta

# England and Wales bank holidays across the data period.
BANK_HOLIDAYS = frozenset(
    date.fromisoformat(d)
    for d in [
        "2025-08-25",
        "2025-12-25",
        "2025-12-26",
        "2026-01-01",
        "2026-04-03",
        "2026-04-06",
        "2026-05-04",
        "2026-05-25",
        "2026-08-31",
        "2026-12-25",
        "2026-12-28",
        "2027-01-01",
        "2027-03-26",
        "2027-03-29",
        "2027-05-03",
        "2027-05-31",
    ]
)
DAY_START_HOUR = 9
DAY_MINUTES = 480  # 09:00 to 17:00


class WorkingCalendar:
    """Maps working minutes since an origin to wall-clock time and back."""

    def __init__(self, origin: date, days: int = 700) -> None:
        self.days = [d for d in (origin + timedelta(n) for n in range(days)) if is_working_day(d)]

    def to_datetime(self, minute: float) -> datetime:
        index, rest = divmod(minute, DAY_MINUTES)
        day = self.days[int(index)]
        start = datetime(day.year, day.month, day.day, DAY_START_HOUR)
        return (start + timedelta(minutes=rest)).replace(microsecond=0)

    def to_minutes(self, moment: datetime) -> float:
        """Out-of-hours moments count as the next opening time."""
        index = bisect_left(self.days, moment.date())
        if index == len(self.days):
            raise ValueError(f"{moment} is outside the calendar")
        if self.days[index] != moment.date():
            return float(index * DAY_MINUTES)
        opened = datetime(moment.year, moment.month, moment.day, DAY_START_HOUR)
        rest = (moment - opened).total_seconds() / 60
        return index * DAY_MINUTES + min(max(rest, 0.0), float(DAY_MINUTES))


def is_working_day(day: date) -> bool:
    return day.weekday() < 5 and day not in BANK_HOLIDAYS
