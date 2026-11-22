"""Per-conversation state the harness owns (not the model).

The model can *ask* to do things; only this state, updated by tools after policy checks,
records what actually happened. Output guards compare the final reply against it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Handoff:
    queue: str
    reason: str
    priority: str
    ticket_id: int


@dataclass
class SessionState:
    session_id: str
    verified_account: str | None = None
    failed_verifications: int = 0
    credits_applied: list[dict[str, Any]] = field(default_factory=list)
    bookings: list[dict[str, Any]] = field(default_factory=list)
    tickets: list[int] = field(default_factory=list)
    handoff: Handoff | None = None
    line_tests: dict[str, dict[str, Any]] = field(default_factory=dict)
    injection_suspected: bool = False
    guardrail_events: list[dict[str, Any]] = field(default_factory=list)
    cited_articles: list[str] = field(default_factory=list)

    @property
    def total_credited(self) -> float:
        return round(sum(c["amount_gbp"] for c in self.credits_applied), 2)

    def record_guardrail(self, kind: str, detail: str, source: str) -> None:
        self.guardrail_events.append({"kind": kind, "detail": detail, "source": source})

    def as_dict(self) -> dict[str, Any]:
        return {
            "verified_account": self.verified_account,
            "credits_applied": self.credits_applied,
            "bookings": self.bookings,
            "tickets": self.tickets,
            "handoff": self.handoff.__dict__ if self.handoff else None,
            "injection_suspected": self.injection_suspected,
            "guardrail_events": self.guardrail_events,
        }
