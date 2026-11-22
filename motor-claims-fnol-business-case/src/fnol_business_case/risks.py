"""Risk register: scoring, RAG ratings and residual-risk reduction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Risk:
    id: str
    risk: str
    category: str
    likelihood: int
    impact: int
    owner: str
    mitigation: str
    residual_likelihood: int
    residual_impact: int

    def __post_init__(self) -> None:
        for v in (self.likelihood, self.impact, self.residual_likelihood, self.residual_impact):
            if not 1 <= v <= 5:
                raise ValueError(f"{self.id}: scores must be 1-5")
        if self.residual_score > self.score:
            raise ValueError(f"{self.id}: residual score exceeds inherent score")

    @property
    def score(self) -> int:
        return self.likelihood * self.impact

    @property
    def residual_score(self) -> int:
        return self.residual_likelihood * self.residual_impact


def rag(score: int) -> str:
    return "Red" if score >= 15 else "Amber" if score >= 8 else "Green"


def load(path: Path) -> list[Risk]:
    return [Risk(**r) for r in json.loads(path.read_text(encoding="utf-8"))]


def to_markdown(risks: list[Risk]) -> str:
    lines = [
        "| ID | Risk | Category | L x I | Rating | Owner | Mitigation | Residual |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(risks, key=lambda r: -r.score):
        lines.append(
            f"| {r.id} | {r.risk} | {r.category} | {r.likelihood}x{r.impact}={r.score} "
            f"| {rag(r.score)} | {r.owner} | {r.mitigation} | {r.residual_score} "
            f"({rag(r.residual_score)}) |"
        )
    total, resid = sum(r.score for r in risks), sum(r.residual_score for r in risks)
    lines.append("")
    lines.append(
        f"Total exposure falls from {total} to {resid} "
        f"({1 - resid / total:.0%} reduction) after mitigation."
    )
    return "\n".join(lines)
