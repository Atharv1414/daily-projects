"""Stakeholder analysis (power/interest) and a RACI matrix with gap analysis."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

VALID = {"R", "A", "C", "I"}


@dataclass(frozen=True)
class Stakeholder:
    name: str
    role: str
    power: int
    interest: int
    stance: str
    concern: str

    @property
    def quadrant(self) -> str:
        high_p, high_i = self.power >= 3, self.interest >= 3
        if high_p and high_i:
            return "Manage closely"
        if high_p:
            return "Keep satisfied"
        if high_i:
            return "Keep informed"
        return "Monitor"


@dataclass(frozen=True)
class RaciFinding:
    severity: str  # "error" | "gap" | "warning"
    activity: str
    message: str


def load(path: Path) -> tuple[list[Stakeholder], dict[str, dict[str, str]]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    people = [Stakeholder(**s) for s in raw["stakeholders"]]
    return people, raw["raci"]


def analyse_raci(
    people: list[Stakeholder], raci: dict[str, dict[str, str]], max_accountable: int = 3
) -> list[RaciFinding]:
    """Rules: exactly one A per activity; at least one R; only known people and codes.

    Also flags people accountable for too many activities and high-power stakeholders who are
    not even informed of the go-live decision.
    """
    names = {p.name for p in people}
    findings: list[RaciFinding] = []
    for activity, row in raci.items():
        for person, code in row.items():
            if person not in names:
                findings.append(RaciFinding("error", activity, f"unknown person {person!r}"))
            if code not in VALID:
                findings.append(RaciFinding("error", activity, f"invalid code {code!r}"))
        codes = Counter(row.values())
        if codes["A"] != 1:
            findings.append(
                RaciFinding("error", activity, f"needs exactly one Accountable, has {codes['A']}")
            )
        if codes["R"] == 0:
            findings.append(
                RaciFinding(
                    "gap",
                    activity,
                    "no one is Responsible; the Accountable person would be doing "
                    "the work by default",
                )
            )
    accountable = Counter(p for row in raci.values() for p, c in row.items() if c == "A")
    for person, n in accountable.items():
        if n > max_accountable:
            findings.append(
                RaciFinding("warning", "(overall)", f"{person} is Accountable for {n} activities")
            )
    golive = next((row for act, row in raci.items() if "go-live" in act.lower()), {})
    for p in people:
        if p.power >= 4 and p.name not in golive:
            findings.append(
                RaciFinding(
                    "gap",
                    "Go-live decision",
                    f"high-power stakeholder {p.name} is not consulted or informed",
                )
            )
    return findings


def raci_markdown(people: list[Stakeholder], raci: dict[str, dict[str, str]]) -> str:
    cols = [p.name for p in people if any(p.name in row for row in raci.values())]
    lines = ["| Activity | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for act, row in raci.items():
        lines.append(f"| {act} | " + " | ".join(row.get(c, "") for c in cols) + " |")
    return "\n".join(lines)


def register_markdown(people: list[Stakeholder]) -> str:
    lines = [
        "| Stakeholder | Role | Power | Interest | Quadrant | Stance | Key concern |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in sorted(people, key=lambda p: (-p.power, -p.interest)):
        lines.append(
            f"| {p.name} | {p.role} | {p.power} | {p.interest} | {p.quadrant} | "
            f"{p.stance} | {p.concern} |"
        )
    return "\n".join(lines)
