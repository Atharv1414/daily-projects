"""Domain types shared by the simulation, the mining code and the report."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum

from .calendar import DAY_MINUTES


class Hazard(StrEnum):
    EMERGENCY = "emergency"
    SIGNIFICANT = "significant"
    ROUTINE = "routine"


class Activity(StrEnum):
    REPORT = "Report received"
    TRIAGE = "Triage"
    DESK = "Desk assessment"
    SURVEY = "Survey visit"
    NO_ACCESS = "Survey: no access"
    SUMMARY = "Written summary sent"
    MAKE_SAFE = "Make safe"
    PARTS = "Parts ordered"
    REPAIR = "Repair"
    INSPECT = "Post inspection"
    CLOSE = "Case closed"


@dataclass(frozen=True)
class Clock:
    """A time limit from one milestone to another, in working days."""

    key: str
    label: str
    limit_days: float
    hazards: frozenset[Hazard]

    @property
    def limit_minutes(self) -> float:
        return self.limit_days * DAY_MINUTES


# A simplified reading of the Hazards in Social Housing (Prescribed Requirements) (England)
# Regulations 2025 ("Awaab's Law"), in force from 27 October 2025. The 24-hour emergency limit
# is approximated as one working day. Not legal advice.
CLOCKS = (
    Clock("emergency", "Emergency made safe in 24 hours", 1, frozenset({Hazard.EMERGENCY})),
    Clock("investigate", "Investigated in 10 working days", 10, frozenset({Hazard.SIGNIFICANT})),
    Clock(
        "summary",
        "Written summary in 3 working days",
        3,
        frozenset({Hazard.SIGNIFICANT, Hazard.EMERGENCY}),
    ),
    Clock("make_safe", "Made safe in 5 working days", 5, frozenset({Hazard.SIGNIFICANT})),
    Clock("repair", "Further works begun in 12 weeks", 60, frozenset({Hazard.SIGNIFICANT})),
)
CLOCK = {c.key: c for c in CLOCKS}


@dataclass(frozen=True)
class Parameters:
    """Everything about the process that can be measured or changed."""

    arrivals_per_day: float = 25.0
    seasonal_swing: float = 0.26  # winter peak and summer trough around the mean
    hazard_mix: tuple[float, float, float] = (0.06, 0.44, 0.50)
    triage_officers: int = 2
    surveyors: int = 8
    admin_officers: int = 1
    crews: int = 18
    triage_minutes: float = 24.0
    survey_minutes: float = 85.0
    no_access_minutes: float = 35.0
    summary_minutes: float = 38.0
    make_safe_minutes: float = 105.0
    repair_minutes: float = 235.0
    inspect_minutes: float = 50.0
    no_access_rate: float = 0.18
    rebook_days: float = 4.0
    parts_rate: float = 0.35
    parts_days: float = 7.0
    repeat_repair_rate: float = 0.20
    inspect_rate: float = 1.0
    desk_rate: float = 0.0  # share of non-emergency cases assessed from photos
    desk_minutes: float = 20.0
    desk_miss_rate: float = 0.08  # desk assessments that still need a visit
    deadline_queue: bool = False  # earliest deadline first, rather than first come first served

    def __post_init__(self) -> None:
        if abs(sum(self.hazard_mix) - 1) > 1e-6:
            raise ValueError("hazard mix must sum to 1")
        for name in (
            "no_access_rate", "parts_rate", "repeat_repair_rate", "inspect_rate", "desk_rate",
            "desk_miss_rate",
        ):  # fmt: skip
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if min(self.triage_officers, self.surveyors, self.admin_officers, self.crews) < 1:
            raise ValueError("every team needs at least one person")

    def change(self, **changes: object) -> Parameters:
        return replace(self, **changes)


@dataclass
class CaseRecord:
    """Milestones of one case, in working minutes. None means not reached."""

    case_id: int
    hazard: Hazard
    reported: float
    investigated: float | None = None
    summarised: float | None = None
    made_safe: float | None = None
    repair_started: float | None = None
    closed: float | None = None
    visits: dict[Activity, int] = field(default_factory=dict)

    def elapsed(self, clock: Clock) -> tuple[float, float | None] | None:
        """(start, end) for a clock, or None if it does not apply or has not started."""
        if self.hazard not in clock.hazards:
            return None
        start, end = {
            "emergency": (self.reported, self.made_safe),
            "investigate": (self.reported, self.investigated),
            "summary": (self.investigated, self.summarised),
            "make_safe": (self.investigated, self.made_safe),
            "repair": (self.investigated, self.repair_started),
        }[clock.key]
        return None if start is None else (start, end)

    def outcome(self, clock: Clock, now: float) -> bool | None:
        """True if met, False if breached, None if not applicable or still within its limit.
        An open case past its limit is a breach: waiting for it to finish would hide it."""
        span = self.elapsed(clock)
        if span is None:
            return None
        start, end = span
        if end is None:
            return False if bool(now - start > clock.limit_minutes) else None
        return bool(end - start <= clock.limit_minutes)


@dataclass(frozen=True)
class Event:
    case_id: int
    hazard: Hazard
    activity: Activity
    start: float
    end: float
    resource: str
