"""Product backlog: validated user stories, MoSCoW rules, WSJF ordering and Gherkin export."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

MoSCoW = Literal["Must", "Should", "Could", "Won't"]
MOSCOW_ORDER = {"Must": 0, "Should": 1, "Could": 2, "Won't": 3}
FIBONACCI = {1, 2, 3, 5, 8, 13, 21}


class Scenario(BaseModel):
    scenario: str = Field(min_length=5)
    given: list[str] = Field(min_length=1)
    when: list[str] = Field(min_length=1)
    then: list[str] = Field(min_length=1)

    def gherkin(self) -> str:
        lines = [f"  Scenario: {self.scenario}"]
        for keyword, items in (("Given", self.given), ("When", self.when), ("Then", self.then)):
            for i, item in enumerate(items):
                lines.append(f"    {keyword if i == 0 else 'And'} {item}")
        return "\n".join(lines)


class Story(BaseModel):
    id: str = Field(pattern=r"^FNOL-\d{2}$")
    epic: str
    as_a: str
    i_want: str
    so_that: str
    moscow: MoSCoW
    points: int
    business_value: int = Field(ge=1, le=10)
    time_criticality: int = Field(ge=1, le=10)
    risk_reduction: int = Field(ge=1, le=10)
    depends_on: list[str] = Field(default_factory=list)
    acceptance: list[Scenario] = Field(min_length=1)

    @field_validator("points")
    @classmethod
    def fibonacci(cls, v: int) -> int:
        if v not in FIBONACCI:
            raise ValueError(f"story points must be Fibonacci {sorted(FIBONACCI)}")
        return v

    @property
    def cost_of_delay(self) -> int:
        return self.business_value + self.time_criticality + self.risk_reduction

    @property
    def wsjf(self) -> float:
        """Weighted shortest job first: cost of delay / job size."""
        return round(self.cost_of_delay / self.points, 2)

    @property
    def statement(self) -> str:
        return f"As a {self.as_a}, I want {self.i_want}, so that {self.so_that}."


class BacklogIssue(BaseModel):
    severity: Literal["error", "warning"]
    message: str


def load_backlog(path: Path) -> list[Story]:
    return [Story.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]


def validate_backlog(stories: list[Story], must_effort_cap: float = 0.6) -> list[BacklogIssue]:
    issues: list[BacklogIssue] = []
    ids = Counter(s.id for s in stories)
    issues += [
        BacklogIssue(severity="error", message=f"duplicate story id {i}")
        for i, n in ids.items()
        if n > 1
    ]
    by_id = {s.id: s for s in stories}
    for s in stories:
        for dep in s.depends_on:
            if dep not in by_id:
                issues.append(
                    BacklogIssue(severity="error", message=f"{s.id} depends on unknown {dep}")
                )
            elif MOSCOW_ORDER[by_id[dep].moscow] > MOSCOW_ORDER[s.moscow]:
                issues.append(
                    BacklogIssue(
                        severity="error",
                        message=f"{s.id} ({s.moscow}) depends on {dep} ({by_id[dep].moscow}): a "
                        "higher priority story cannot depend on a lower one",
                    )
                )
        if s.moscow == "Must" and len(s.acceptance) < 2:
            issues.append(
                BacklogIssue(
                    severity="warning",
                    message=f"{s.id} is a Must with only one scenario; add an unhappy path",
                )
            )
    cycle = find_cycle(stories)
    if cycle:
        issues.append(
            BacklogIssue(severity="error", message="dependency cycle: " + " -> ".join(cycle))
        )
    in_scope = [s for s in stories if s.moscow != "Won't"]
    must_share = sum(s.points for s in in_scope if s.moscow == "Must") / max(
        1, sum(s.points for s in in_scope)
    )
    if must_share > must_effort_cap:
        issues.append(
            BacklogIssue(
                severity="warning",
                message=f"Musts are {must_share:.0%} of in-scope effort; DSDM guidance is at most "
                f"{must_effort_cap:.0%} so Shoulds/Coulds act as contingency",
            )
        )
    return issues


def find_cycle(stories: list[Story]) -> list[str] | None:
    graph = {s.id: s.depends_on for s in stories}
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                return stack[stack.index(nxt) :] + [nxt]
            if nxt in graph and state.get(nxt) is None:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return None

    for node in graph:
        if state.get(node) is None:
            found = visit(node)
            if found:
                return found
    return None


def prioritised(stories: list[Story]) -> list[Story]:
    """MoSCoW first, then WSJF descending; dependencies are then pulled ahead (stable)."""
    ranked = sorted(stories, key=lambda s: (MOSCOW_ORDER[s.moscow], -s.wsjf, s.id))
    placed: list[Story] = []
    done: set[str] = set()
    by_id = {s.id: s for s in stories}

    def place(s: Story) -> None:
        if s.id in done:
            return
        for dep in s.depends_on:
            if dep in by_id:
                place(by_id[dep])
        done.add(s.id)
        placed.append(s)

    for s in ranked:
        place(s)
    return placed


def to_markdown(stories: list[Story], issues: list[BacklogIssue]) -> str:
    lines = [
        "# Prioritised backlog",
        "",
        "Ordered by MoSCoW, then WSJF (cost of delay / story points), with dependencies "
        "pulled ahead.",
        "",
        "| # | ID | MoSCoW | Story | Pts | WSJF | Depends on |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, s in enumerate(prioritised(stories), 1):
        lines.append(
            f"| {i} | {s.id} | {s.moscow} | {s.statement} | {s.points} | {s.wsjf} | "
            f"{', '.join(s.depends_on) or '-'} |"
        )
    totals = Counter()
    for s in stories:
        totals[s.moscow] += s.points
    lines += [
        "",
        "**Effort by priority:** "
        + ", ".join(f"{k} {totals[k]} pts" for k in MOSCOW_ORDER if totals[k]),
        "",
        "## Validation",
        "",
    ]
    lines += [f"- {i.severity.upper()}: {i.message}" for i in issues] or ["- No issues."]
    lines += ["", "## Acceptance criteria", ""]
    for s in prioritised(stories):
        lines += [f"### {s.id}: {s.i_want}", "", "```gherkin", feature(s), "```", ""]
    return "\n".join(lines)


def feature(story: Story) -> str:
    head = [f"Feature: {story.i_want[0].upper()}{story.i_want[1:]}", f"  {story.statement}", ""]
    return "\n".join(head) + "\n\n".join(sc.gherkin() for sc in story.acceptance)


def export_features(stories: list[Story], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for s in stories:
        if s.moscow == "Won't":
            continue
        p = out_dir / f"{s.id.lower()}.feature"
        p.write_text(feature(s) + "\n", encoding="utf-8")
        paths.append(p)
    return paths
