"""Runs the whole analysis once and keeps the results together."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import datagen, eventlog, finance, mining, simulation
from .content import Content, Story, load
from .eventlog import CleanLog
from .model import CaseRecord, Parameters
from .simulation import Estimate, paired_difference, replicate, scenarios

BASE = "A. Do nothing"
RECOMMENDED = "D. Deadline queue + 1 admin"
DIGITAL = "E. Digital process"
HALF = "E2. Digital, half effect"
STRESS = 1.15  # demand in the stress test, against today
# Stories that higher is better for; the rest are counts or durations to bring down.
_HIGHER = ("met_", "conformance")


@dataclass
class Analysis:
    log: CleanLog
    records: list[CaseRecord]
    now: float
    compliance: pd.DataFrame
    conformance: mining.Conformance
    parameters: Parameters
    runs: dict[str, dict[str, list[float]]]
    options: dict[str, finance.Option]
    assumptions: finance.Assumptions
    content: Content
    stressed: dict[str, dict[str, list[float]]]

    def mean(self, scenario: str, key: str) -> Estimate:
        return Estimate.of(self.runs[scenario][key])

    def change(self, scenario: str, key: str) -> Estimate:
        return paired_difference(self.runs[BASE][key], self.runs[scenario][key])

    def observed(self) -> dict[str, float]:
        """The same measures from the log, to validate the calibrated model against."""
        closed = [c for c in self.records if c.closed is not None]
        days = [(c.closed - c.reported) / 480 for c in closed]
        out = {f"met_{r.key}": r.met_share for r in self.compliance.itertuples()}
        out["mean_days"] = sum(days) / len(days)
        out["no_access_visits"] = float((self.log.events.activity == "Survey: no access").sum())
        return out

    def story_result(self, story: Story) -> tuple[float | None, bool | None]:
        """Simulated value and whether it meets the target. None if the model cannot say."""
        option = RECOMMENDED if story.phase == 1 else DIGITAL
        if story.priority == "Won't" or story.kpi not in self.runs[option]:
            return None, None
        value = self.mean(option, story.kpi).mean
        if story.kpi.startswith(_HIGHER):
            return value, value >= story.target
        return value, value <= story.target


def half_effect(base: Parameters, full: Parameters) -> Parameters:
    """Every digital improvement only half delivered (the queue rule is all or nothing)."""
    names = ("desk_rate", "no_access_rate", "rebook_days", "inspect_rate", "summary_minutes",
             "parts_days")  # fmt: skip
    halves = {n: (getattr(base, n) + getattr(full, n)) / 2 for n in names}
    return full.change(**halves)


def run(replications: int = 20, seed: int = 2026) -> Analysis:
    log = eventlog.clean(datagen.event_log(seed))
    records = mining.case_records(log)
    now = float(log.events.end_minute.max())
    parameters = mining.estimate_parameters(log, Parameters())
    choices = scenarios(parameters)
    choices[HALF] = half_effect(parameters, choices[DIGITAL])
    seeds = range(1000, 1000 + replications)
    runs = {name: replicate(p, seeds) for name, p in choices.items()}

    busier = parameters.arrivals_per_day * STRESS
    stressed = {
        name: replicate(p.change(arrivals_per_day=busier), seeds)
        for name, p in choices.items()
        if name != HALF
    }

    options = {}
    for name, p in choices.items():
        avoided = -paired_difference(
            runs[BASE]["breached_cases"], runs[name]["breached_cases"]
        ).mean
        options[name] = finance.Option(
            name,
            avoided * simulation.YEAR_DAYS / (simulation.HORIZON_DAYS - simulation.WARM_UP_DAYS),
            p.surveyors - parameters.surveyors,
            p.crews - parameters.crews,
            p.admin_officers - parameters.admin_officers,
            digital=p.desk_rate > 0,
            queue_only=p.deadline_queue and p.desk_rate == 0,
        )
    return Analysis(
        log,
        records,
        now,
        mining.compliance(records, now),
        mining.check_conformance(log),
        parameters,
        runs,
        options,
        finance.Assumptions(),
        load(),
        stressed,
    )
