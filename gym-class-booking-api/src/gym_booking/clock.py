"""An injectable clock so time-based business rules can be tested deterministically."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Return the current time as a naive UTC datetime (how it is stored in SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FixedClock:
    """A clock that returns a set time until it is moved on. Used by tests and the demo."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        """Move the clock forward, e.g. ``clock.advance(hours=3)``."""
        from datetime import timedelta

        self.now = self.now + timedelta(**delta)
