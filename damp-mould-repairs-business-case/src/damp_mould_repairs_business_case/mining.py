"""Process mining: what actually happens, how it differs from policy and where time goes."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .calendar import DAY_MINUTES
from .eventlog import CleanLog
from .model import CLOCKS, Activity, CaseRecord, Hazard, Parameters

A = Activity
START, END = "START", "END"

# Policy: which activity may directly follow which. The written summary runs in parallel with
# the works, so it is checked as a required activity instead of a position in the sequence.
POLICY: dict[str, frozenset[str]] = {
    START: frozenset({A.REPORT}),
    A.REPORT: frozenset({A.TRIAGE}),
    A.TRIAGE: frozenset({A.SURVEY, A.NO_ACCESS, A.MAKE_SAFE}),
    A.NO_ACCESS: frozenset({A.SURVEY, A.NO_ACCESS}),
    A.SURVEY: frozenset({A.MAKE_SAFE, A.PARTS, A.REPAIR}),
    A.MAKE_SAFE: frozenset({A.PARTS, A.REPAIR, A.SURVEY, A.NO_ACCESS}),
    A.PARTS: frozenset({A.REPAIR}),
    A.REPAIR: frozenset({A.REPAIR, A.INSPECT}),
    A.INSPECT: frozenset({A.CLOSE}),
    A.CLOSE: frozenset({END}),
}


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    count: int
    median_wait_days: float


def traces(log: CleanLog) -> dict[str, list[str]]:
    sequence = log.events[log.events.activity != A.SUMMARY.value]
    return {case: list(rows) for case, rows in sequence.groupby("case_id").activity}


def variants(log: CleanLog, top: int = 8) -> list[tuple[tuple[str, ...], int, float]]:
    counts = Counter(tuple(t) for t in traces(log).values())
    total = sum(counts.values())
    return [(v, n, n / total) for v, n in counts.most_common(top)]


def directly_follows(log: CleanLog) -> list[Edge]:
    """Edges with the working time between one activity ending and the next starting."""
    gaps: dict[tuple[str, str], list[float]] = defaultdict(list)
    counts: Counter[tuple[str, str]] = Counter()
    rows = log.events[log.events.activity != A.SUMMARY.value]
    for _, case in rows.groupby("case_id"):
        names = case.activity.to_list()
        ends, starts = case.end_minute.to_list(), case.start_minute.to_list()
        for i in range(1, len(names)):
            edge = (names[i - 1], names[i])
            counts[edge] += 1
            if not np.isnan(starts[i]):
                gaps[edge].append(max(0.0, starts[i] - ends[i - 1]) / DAY_MINUTES)
    return sorted(
        (
            Edge(s, t, n, float(np.median(gaps[s, t])) if gaps[s, t] else float("nan"))
            for (s, t), n in counts.items()
        ),
        key=lambda e: (-e.count, e.source, e.target),
    )


@dataclass(frozen=True)
class Conformance:
    fitness: float  # share of steps that policy allows
    conforming_cases: float
    violations: list[tuple[str, int]]


def check_conformance(log: CleanLog) -> Conformance:
    steps = allowed = clean_cases = total = 0
    found: Counter[str] = Counter()
    summaries = set(log.events.loc[log.events.activity == A.SUMMARY.value, "case_id"])
    hazard = log.events.groupby("case_id").hazard.first()
    for case, names in traces(log).items():
        total += 1
        path = [START, *names]
        finished = names[-1] == A.CLOSE
        if finished:
            path.append(END)
        problems = []
        for source, target in zip(path, path[1:], strict=False):
            steps += 1
            if target in POLICY.get(source, ()):
                allowed += 1
            else:
                problems.append(f"{source} → {target}")
        if finished and hazard[case] != Hazard.ROUTINE and case not in summaries:
            problems.append("closed without a written summary")
        found.update(problems)
        clean_cases += not problems
    return Conformance(
        allowed / steps if steps else 1.0,
        clean_cases / total if total else 1.0,
        found.most_common(),
    )


def case_records(log: CleanLog) -> list[CaseRecord]:
    """Rebuilds case milestones from the log, for the same clock rules the simulation uses."""
    records = []
    for case, rows in log.events.groupby("case_id"):
        ends = rows.groupby("activity").end_minute
        last, first = ends.max().to_dict(), ends.min().to_dict()
        repair = rows[rows.activity == A.REPAIR.value]
        started = None
        if len(repair):
            begin = repair.start_minute.iloc[0]
            started = float(repair.end_minute.iloc[0] if np.isnan(begin) else begin)
        records.append(
            CaseRecord(
                case_id=int(str(case).split("-")[1]),
                hazard=Hazard(rows.hazard.iloc[0]),
                reported=first[A.REPORT.value],
                investigated=last.get(A.SURVEY.value),
                summarised=last.get(A.SUMMARY.value),
                made_safe=first.get(A.MAKE_SAFE.value),
                repair_started=started,
                closed=last.get(A.CLOSE.value),
            )
        )
    return records


def compliance(records: list[CaseRecord], now: float) -> pd.DataFrame:
    rows = []
    for clock in CLOCKS:
        answers = [o for c in records if (o := c.outcome(clock, now)) is not None]
        rows.append(
            (clock.key, clock.label, len(answers), sum(answers), len(answers) - sum(answers))
        )
    table = pd.DataFrame(rows, columns=["key", "clock", "cases", "met", "breached"])
    table["met_share"] = table.met / table.cases
    return table


def investigation_by_month(log: CleanLog, records: list[CaseRecord]) -> pd.Series:
    """Share of significant cases investigated in time, by month reported."""
    clock = next(c for c in CLOCKS if c.key == "investigate")
    now = log.events.end_minute.max()
    rows = [
        (log.calendar.to_datetime(c.reported).strftime("%Y-%m"), o)
        for c in records
        if (o := c.outcome(clock, now)) is not None
    ]
    frame = pd.DataFrame(rows, columns=["month", "met"])
    return frame.groupby("month").met.mean()


def time_breakdown(log: CleanLog) -> pd.DataFrame:
    """Working days per closed case spent being worked on and spent waiting, by activity.

    Waiting is measured back to the previous event in the case, so it includes queues, rebooking
    delays and parts lead times."""
    closed = log.events.groupby("case_id").activity.transform(lambda s: s.eq(A.CLOSE).any())
    rows = log.events[closed & (log.events.activity != A.SUMMARY.value)].copy()
    previous = rows.groupby("case_id").end_minute.shift()
    rows["wait"] = (rows.start_minute - previous).clip(lower=0)
    rows["work"] = rows.end_minute - rows.start_minute
    cases = rows.case_id.nunique()
    table = rows.groupby("activity")[["wait", "work"]].sum() / cases / DAY_MINUTES
    return table.sort_values("wait", ascending=False)


def estimate_parameters(log: CleanLog, staffing: Parameters) -> Parameters:
    """Measures the as-is process. Headcounts come from HR, not from the log."""
    events = log.events
    counts = events.activity.value_counts()
    minutes = (events.end_minute - events.start_minute).groupby(events.activity).mean()
    reports = events[events.activity == A.REPORT.value]
    days = np.floor(reports.end_minute / DAY_MINUTES)
    working_days = days.max() - days.min() + 1
    mix = reports.hazard.value_counts(normalize=True)

    # Only the first repair is a fair trial: the process allows at most two repeats.
    repairs = events[events.activity == A.REPAIR.value]
    per_case = repairs.groupby("case_id").size()
    finished = events[events.activity == A.CLOSE.value].case_id
    per_case = per_case[per_case.index.isin(finished)]

    # Parts lead time: ordered until the next repair starts. Crew queueing is included, so the
    # median wait of cases that needed no parts is subtracted.
    edges = {(e.source, e.target): e for e in directly_follows(log)}
    parts = _mean_gap(events, A.PARTS.value, A.REPAIR.value)
    queue = _mean_gap(events, A.MAKE_SAFE.value, A.REPAIR.value)
    rebook = edges[A.NO_ACCESS.value, A.SURVEY.value].median_wait_days
    survey_queue = edges[A.TRIAGE.value, A.SURVEY.value].median_wait_days
    attempts = counts[A.NO_ACCESS.value] + counts[A.SURVEY.value]
    emergency = round(float(mix[Hazard.EMERGENCY]), 4)
    significant = round(float(mix[Hazard.SIGNIFICANT]), 4)
    return staffing.change(
        arrivals_per_day=float(len(reports) / working_days),
        hazard_mix=(emergency, significant, 1 - emergency - significant),
        triage_minutes=float(minutes[A.TRIAGE.value]),
        survey_minutes=float(minutes[A.SURVEY.value]),
        no_access_minutes=float(minutes[A.NO_ACCESS.value]),
        summary_minutes=float(minutes[A.SUMMARY.value]),
        make_safe_minutes=float(minutes[A.MAKE_SAFE.value]),
        repair_minutes=float(minutes[A.REPAIR.value]),
        inspect_minutes=float(minutes[A.INSPECT.value]),
        no_access_rate=float(counts[A.NO_ACCESS.value] / attempts),
        rebook_days=float(max(1.0, rebook - survey_queue)),
        parts_rate=float(counts[A.PARTS.value] / repairs.case_id.nunique()),
        parts_days=float(max(1.0, parts - queue)),
        repeat_repair_rate=float((per_case > 1).mean()),
    )


def _mean_gap(events: pd.DataFrame, source: str, target: str) -> float:
    # The written summary runs in parallel, so it must not break up the sequence.
    events = events[events.activity != A.SUMMARY.value]
    previous = events.groupby("case_id").activity.shift()
    ended = events.groupby("case_id").end_minute.shift()
    rows = (previous == source) & (events.activity == target)
    return float(((events.start_minute - ended)[rows].clip(lower=0)).mean() / DAY_MINUTES)
