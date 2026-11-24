"""Loads the analyst's content and enforces the rules that keep it coherent."""

from __future__ import annotations

import tomllib
from collections import Counter
from dataclasses import dataclass
from importlib import resources
from typing import Any

PRIORITIES = ("Must", "Should", "Could", "Won't")
# DSDM guidance: Must-haves should take no more than 60% of effort.
MAX_MUST_SHARE = 0.60


class ContentError(ValueError):
    """The content breaks a rule."""


@dataclass(frozen=True)
class Story:
    id: str
    priority: str
    points: int
    solves: tuple[str, ...]
    role: str
    want: str
    so: str
    kpi: str
    target: float
    phase: int
    given: str
    when: str
    then: str

    def gherkin(self) -> str:
        return (
            f"  Scenario: {self.id} {self.want}\n    Given {self.given}\n"
            f"    When {self.when}\n    Then {self.then}\n"
        )


@dataclass(frozen=True)
class Content:
    stories: tuple[Story, ...]
    pain_points: dict[str, dict[str, str]]
    stakeholders: tuple[dict[str, str], ...]
    risks: tuple[dict[str, Any], ...]
    raci_roles: tuple[str, ...]
    raci: dict[str, tuple[str, ...]]

    @property
    def in_scope(self) -> list[Story]:
        return [s for s in self.stories if s.priority != "Won't"]


def load(text: str | None = None) -> Content:
    if text is None:
        folder = resources.files("damp_mould_repairs_business_case") / "content"
        text = (folder / "analysis.toml").read_text()
    data = tomllib.loads(text)
    content = Content(
        stories=tuple(Story(**{**s, "solves": tuple(s["solves"])}) for s in data["stories"]),
        pain_points={p["id"]: p for p in data["pain_points"]},
        stakeholders=tuple(data["stakeholders"]),
        risks=tuple(data["risks"]),
        raci_roles=tuple(data["raci"]["roles"]),
        raci={a["name"]: tuple(a["codes"]) for a in data["raci"]["activities"]},
    )
    problems = validate(content)
    if problems:
        raise ContentError("; ".join(problems))
    return content


def validate(content: Content) -> list[str]:
    problems = []
    repeated = [i for i, n in Counter(s.id for s in content.stories).items() if n > 1]
    if repeated:
        problems.append(f"duplicate story ids {repeated}")
    covered: set[str] = set()
    for story in content.stories:
        if story.priority not in PRIORITIES:
            problems.append(f"{story.id}: unknown priority {story.priority!r}")
        unknown = set(story.solves) - set(content.pain_points)
        if unknown or not story.solves:
            problems.append(f"{story.id}: does not trace to a known pain point")
        if story.priority != "Won't":
            covered |= set(story.solves)
    for missing in sorted(set(content.pain_points) - covered):
        problems.append(f"{missing}: no in-scope story addresses it")
    effort = sum(s.points for s in content.in_scope)
    must = sum(s.points for s in content.in_scope if s.priority == "Must")
    if effort and must / effort > MAX_MUST_SHARE:
        problems.append(f"Must-haves are {must / effort:.0%} of effort")
    for activity, codes in content.raci.items():
        if len(codes) != len(content.raci_roles):
            problems.append(f"RACI {activity!r}: wrong number of roles")
        if codes.count("A") != 1:
            problems.append(f"RACI {activity!r}: needs exactly one accountable role")
        if "R" not in codes and "A" in codes:
            problems.append(f"RACI {activity!r}: nobody is responsible")
        if set(codes) - {"R", "A", "C", "I", ""}:
            problems.append(f"RACI {activity!r}: unknown code")
    for risk in content.risks:
        if not (1 <= risk["probability"] <= 5 and 1 <= risk["impact"] <= 5):
            problems.append(f"{risk['id']}: scores must be 1 to 5")
    return problems
