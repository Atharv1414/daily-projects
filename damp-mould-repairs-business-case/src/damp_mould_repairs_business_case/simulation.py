"""Discrete-event simulation of the repairs process on a working-time axis."""

from __future__ import annotations

import heapq
import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from .calendar import DAY_MINUTES
from .model import CLOCK, CLOCKS, Activity, CaseRecord, Event, Hazard, Parameters

YEAR_DAYS = 253


@dataclass(frozen=True)
class Draws:
    """All randomness for one case, drawn up front. Scenarios that share a seed see the same
    cases with the same luck, so differences between them come from the change itself."""

    hazard: float
    arrival: float
    work: np.ndarray  # service-time multipliers
    chance: np.ndarray  # uniform draws for yes/no outcomes
    parts: float


def draw_cases(params: Parameters, days: int, seed: int) -> list[Draws]:
    rng = np.random.default_rng(seed)
    peak = params.arrivals_per_day * (1 + params.seasonal_swing)
    count = int(rng.poisson(peak * days))
    times = np.sort(rng.random(count)) * days
    # Thinning. Day zero is early September; the peak falls in mid January.
    season = 1 + params.seasonal_swing * np.cos(2 * math.pi * (times - 92) / YEAR_DAYS)
    kept = times[rng.random(count) < season / (1 + params.seasonal_swing)]
    n = len(kept)
    hazard, parts = rng.random(n), rng.exponential(1.0, n)
    work = rng.lognormal(-0.125 / 2, math.sqrt(0.125), (n, 12))  # mean one
    chance = rng.random((n, 14))
    return [
        Draws(hazard[i], float(kept[i]) * DAY_MINUTES, work[i], chance[i], parts[i])
        for i in range(n)
    ]


class Resource:
    """A pool of identical people with a priority queue. Work is never interrupted."""

    def __init__(self, sim: Simulation, name: str, capacity: int) -> None:
        self.name = name
        self.capacity = capacity
        self.busy_minutes = 0.0
        self._sim = sim
        self._free = list(range(capacity))
        self._queue: list[tuple[float, int, float, Callable[[int], None]]] = []

    def request(self, priority: float, minutes: float, done: Callable[[float, str], None]) -> None:
        """Calls done(start, person) when the work completes."""

        def begin(person: int) -> None:
            start = self._sim.now
            self.busy_minutes += minutes
            label = f"{self.name}-{person + 1:02d}"

            def finish() -> None:
                heapq.heappush(self._free, person)
                done(start, label)
                self._dispatch()

            self._sim.after(minutes, finish)

        heapq.heappush(self._queue, (priority, next(self._sim.sequence), minutes, begin))
        self._dispatch()

    def _dispatch(self) -> None:
        while self._free and self._queue:
            _, _, _, begin = heapq.heappop(self._queue)
            begin(heapq.heappop(self._free))

    @property
    def waiting(self) -> int:
        return len(self._queue)


@dataclass
class Result:
    cases: list[CaseRecord]
    events: list[Event]
    utilisation: dict[str, float]
    warm_up: float
    horizon: float
    counts: dict[Activity, int] = field(default_factory=dict)

    @property
    def measured(self) -> list[CaseRecord]:
        return [c for c in self.cases if c.reported >= self.warm_up]


class Simulation:
    def __init__(self, params: Parameters, draws: list[Draws], horizon_days: float) -> None:
        self.params = params
        self.now = 0.0
        self.sequence = itertools.count()
        self._horizon = horizon_days * DAY_MINUTES
        self._events: list[tuple[float, int, Callable[[], None]]] = []
        self._log: list[Event] = []
        self._cases: list[CaseRecord] = []
        self.triage = Resource(self, "triage", params.triage_officers)
        self.surveyors = Resource(self, "surveyor", params.surveyors)
        self.admin = Resource(self, "admin", params.admin_officers)
        self.crews = Resource(self, "crew", params.crews)
        for number, draw in enumerate(draws, start=1):
            self.at(draw.arrival, _Case(self, number, draw).report)

    def at(self, time: float, action: Callable[[], None]) -> None:
        heapq.heappush(self._events, (time, next(self.sequence), action))

    def after(self, delay: float, action: Callable[[], None]) -> None:
        self.at(self.now + delay, action)

    def log(self, record: CaseRecord, activity: Activity, start: float, who: str) -> None:
        record.visits[activity] = record.visits.get(activity, 0) + 1
        self._log.append(Event(record.case_id, record.hazard, activity, start, self.now, who))

    def add(self, record: CaseRecord) -> None:
        self._cases.append(record)

    def run(self, warm_up_days: float) -> Result:
        while self._events and self._events[0][0] <= self._horizon:
            self.now, _, action = heapq.heappop(self._events)
            action()
        pools = (self.triage, self.surveyors, self.admin, self.crews)
        result = Result(
            self._cases,
            self._log,
            {p.name: p.busy_minutes / (p.capacity * self._horizon) for p in pools},
            warm_up_days * DAY_MINUTES,
            self._horizon,
        )
        for event in self._log:
            if event.end >= result.warm_up:
                result.counts[event.activity] = result.counts.get(event.activity, 0) + 1
        return result


class _Case:
    """One case walking through the process. Each method schedules the next step."""

    def __init__(self, sim: Simulation, number: int, draws: Draws) -> None:
        mix = sim.params.hazard_mix
        hazard = (
            Hazard.EMERGENCY
            if draws.hazard < mix[0]
            else Hazard.SIGNIFICANT
            if draws.hazard < mix[0] + mix[1]
            else Hazard.ROUTINE
        )
        self.sim, self.p, self.draws = sim, sim.params, draws
        self.record = CaseRecord(number, hazard, draws.arrival)
        self.attempts = 0

    def _priority(self, clock: str | None, start: float, fallback_days: float) -> float:
        """Emergencies always jump the queue. Otherwise the as-is process is first come, first
        served, and the improved one is earliest deadline first."""
        if self.record.hazard is Hazard.EMERGENCY:
            return -1e9 + self.sim.now
        if not self.p.deadline_queue:
            return self.sim.now
        applies = clock is not None and self.record.hazard in CLOCK[clock].hazards
        days = CLOCK[clock].limit_days if applies else fallback_days
        return start + days * DAY_MINUTES

    def report(self) -> None:
        self.sim.add(self.record)
        self.sim.log(self.record, Activity.REPORT, self.sim.now, "customer")
        minutes = self.p.triage_minutes * self.draws.work[0]
        self.sim.triage.request(self._priority(None, self.sim.now, 2), minutes, self._triaged)

    def _triaged(self, start: float, who: str) -> None:
        self.sim.log(self.record, Activity.TRIAGE, start, who)
        if self.record.hazard is Hazard.EMERGENCY:
            self._make_safe()
        elif self.draws.chance[0] < self.p.desk_rate:
            minutes = self.p.desk_minutes * self.draws.work[1]
            self.sim.triage.request(
                self._priority("investigate", self.record.reported, 20), minutes, self._desk_done
            )
        else:
            self._survey()

    def _desk_done(self, start: float, who: str) -> None:
        self.sim.log(self.record, Activity.DESK, start, who)
        if self.draws.chance[1] < self.p.desk_miss_rate:
            self._survey()
        else:
            self._investigated()

    def _survey(self) -> None:
        # The fourth attempt always succeeds: the team escalates to a pre-agreed appointment.
        missed = self.attempts < 3 and (
            self.draws.chance[2 + self.attempts] < self.p.no_access_rate
        )
        base = self.p.no_access_minutes if missed else self.p.survey_minutes
        minutes = base * self.draws.work[2 + self.attempts]
        self.attempts += 1
        self.sim.surveyors.request(
            self._priority("investigate", self.record.reported, 20),
            minutes,
            lambda start, who: self._surveyed(missed, start, who),
        )

    def _surveyed(self, missed: bool, start: float, who: str) -> None:
        self.sim.log(self.record, Activity.NO_ACCESS if missed else Activity.SURVEY, start, who)
        if missed:
            self.sim.after(self.p.rebook_days * DAY_MINUTES, self._survey)
        else:
            self._investigated()

    def _investigated(self) -> None:
        self.record.investigated = self.sim.now
        if self.record.hazard is not Hazard.ROUTINE:
            self.sim.admin.request(
                self._priority("summary", self.sim.now, 3),
                self.p.summary_minutes * self.draws.work[6],
                self._summarised,
            )
        if self.record.hazard is Hazard.SIGNIFICANT:
            self._make_safe()
        else:
            self._parts()

    def _summarised(self, start: float, who: str) -> None:
        self.record.summarised = self.sim.now
        self.sim.log(self.record, Activity.SUMMARY, start, who)

    def _make_safe(self) -> None:
        base = self.record.investigated or self.sim.now
        self.sim.crews.request(
            self._priority("make_safe", base, 5),
            self.p.make_safe_minutes * self.draws.work[7],
            self._made_safe,
        )

    def _made_safe(self, start: float, who: str) -> None:
        self.record.made_safe = self.sim.now
        self.sim.log(self.record, Activity.MAKE_SAFE, start, who)
        if self.record.investigated is None:
            self._survey()  # emergencies are made safe first and surveyed afterwards
        else:
            self._parts()

    def _parts(self) -> None:
        if self.draws.chance[6] < self.p.parts_rate:
            self.sim.log(self.record, Activity.PARTS, self.sim.now, "stores")
            self.sim.after(self.p.parts_days * DAY_MINUTES * self.draws.parts, self._repair)
        else:
            self._repair()

    def _repair(self, visit: int = 0) -> None:
        self.sim.crews.request(
            self._priority("repair", self.record.investigated or self.sim.now, 40),
            self.p.repair_minutes * self.draws.work[8 + min(visit, 2)],
            lambda start, who: self._repaired(visit, start, who),
        )

    def _repaired(self, visit: int, start: float, who: str) -> None:
        if self.record.repair_started is None:
            self.record.repair_started = start
        self.sim.log(self.record, Activity.REPAIR, start, who)
        if visit < 2 and self.draws.chance[7 + visit] < self.p.repeat_repair_rate:
            self._repair(visit + 1)
        elif self.draws.chance[10] < self.p.inspect_rate:
            self.sim.surveyors.request(
                self._priority(None, self.sim.now, 15),
                self.p.inspect_minutes * self.draws.work[11],
                self._inspected,
            )
        else:
            self._close()

    def _inspected(self, start: float, who: str) -> None:
        self.sim.log(self.record, Activity.INSPECT, start, who)
        self._close()

    def _close(self) -> None:
        self.record.closed = self.sim.now
        self.sim.log(self.record, Activity.CLOSE, self.sim.now, "system")


WARM_UP_DAYS = 40  # September and October fill the queues before measurement starts
HORIZON_DAYS = WARM_UP_DAYS + YEAR_DAYS


def simulate(params: Parameters, seed: int, horizon_days: int = HORIZON_DAYS) -> Result:
    draws = draw_cases(params, horizon_days, seed)
    return Simulation(params, draws, horizon_days).run(min(WARM_UP_DAYS, horizon_days / 2))


@dataclass(frozen=True)
class Estimate:
    mean: float
    low: float
    high: float

    @classmethod
    def of(cls, values: list[float]) -> Estimate:
        """Normal-approximation 95% interval over replications."""
        data = np.asarray(values, dtype=float)
        spread = 1.96 * data.std(ddof=1) / math.sqrt(len(data)) if len(data) > 1 else 0.0
        return cls(float(data.mean()), float(data.mean() - spread), float(data.mean() + spread))


def summarise(result: Result) -> dict[str, float]:
    """Headline measures of one run. Compliance is a share of cases whose clock has an answer."""
    measured = result.measured
    out: dict[str, float] = {"cases": float(len(measured))}
    breached: set[int] = set()
    for clock in CLOCKS:
        outcomes = [c.outcome(clock, result.horizon) for c in measured]
        answered = [o for o in outcomes if o is not None]
        out[f"met_{clock.key}"] = float(np.mean(answered)) if answered else float("nan")
        breached |= {c.case_id for c, o in zip(measured, outcomes, strict=True) if o is False}
    in_scope = [c for c in measured if c.hazard is not Hazard.ROUTINE]
    out["breached_cases"] = float(len(breached))
    out["compliant_share"] = 1 - len(breached) / len(in_scope) if in_scope else float("nan")
    closed = [c for c in measured if c.closed is not None]
    days = [(c.closed - c.reported) / DAY_MINUTES for c in closed]
    out["mean_days"] = float(np.mean(days)) if days else float("nan")
    out["p90_days"] = float(np.percentile(days, 90)) if days else float("nan")
    out["still_open"] = float(len(measured) - len(closed))
    for name, activity in (
        ("no_access_visits", Activity.NO_ACCESS),
        ("surveys", Activity.SURVEY),
        ("inspections", Activity.INSPECT),
        ("desk_assessments", Activity.DESK),
        ("repairs", Activity.REPAIR),
    ):
        out[name] = float(result.counts.get(activity, 0))
    for pool, share in result.utilisation.items():
        out[f"use_{pool}"] = share
    return out


def replicate(params: Parameters, seeds: range) -> dict[str, list[float]]:
    runs = [summarise(simulate(params, seed)) for seed in seeds]
    return {key: [r[key] for r in runs] for key in runs[0]}


def paired_difference(base: list[float], option: list[float]) -> Estimate:
    """Difference between scenarios run on the same cases: far tighter than two separate CIs."""
    return Estimate.of([o - b for b, o in zip(base, option, strict=True)])


def scenarios(base: Parameters) -> dict[str, Parameters]:
    digital = {
        "deadline_queue": True,
        "desk_rate": 0.35,
        "no_access_rate": base.no_access_rate * 0.45,
        "rebook_days": 2.0,
        "inspect_rate": 0.30,
        "summary_minutes": 12.0,
        "parts_days": base.parts_days * 0.8,
    }
    return {
        "A. Do nothing": base,
        "B. Deadline queue only": base.change(deadline_queue=True),
        "C. Hire 5, same process": base.change(
            surveyors=base.surveyors + 2,
            crews=base.crews + 2,
            admin_officers=base.admin_officers + 1,
        ),
        "D. Deadline queue + 1 admin": base.change(
            deadline_queue=True, admin_officers=base.admin_officers + 1
        ),
        "E. Digital process": base.change(**digital),
        "F. Digital + 2 crews": base.change(**digital, crews=base.crews + 2),
    }
