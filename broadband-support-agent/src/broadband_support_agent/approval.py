"""Human-in-the-loop approval for side-effecting actions."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ApprovalRequest:
    action: str
    account_id: str
    summary: str
    details: dict[str, Any]


class ApprovalPolicy(Protocol):
    def approve(self, request: ApprovalRequest) -> tuple[bool, str]:
        """Return (approved, reviewer id)."""
        ...


class AutoDeny:
    def approve(self, request: ApprovalRequest) -> tuple[bool, str]:
        return False, "policy:auto-deny"


class AutoApprove:
    def approve(self, request: ApprovalRequest) -> tuple[bool, str]:
        return True, "policy:auto-approve"


@dataclass
class ScriptedApproval:
    """Answers approval prompts from a list, recording what was asked (for tests and evals)."""

    answers: list[bool]
    asked: list[ApprovalRequest] = field(default_factory=list)

    def approve(self, request: ApprovalRequest) -> tuple[bool, str]:
        self.asked.append(request)
        answer = self.answers.pop(0) if self.answers else False
        return answer, "reviewer:scripted"


@dataclass
class ConsoleApproval:
    """Asks a human team leader at the terminal."""

    reviewer: str = "team-leader"
    ask: Callable[[str], str] = input

    def approve(self, request: ApprovalRequest) -> tuple[bool, str]:
        print("\n--- APPROVAL REQUIRED ------------------------------------------")
        print(f"Action:  {request.action}  (account {request.account_id})")
        print(f"Summary: {request.summary}")
        print(json.dumps(request.details, indent=2, default=str))
        answer = self.ask("Approve? [y/N] ").strip().lower()
        return answer in {"y", "yes"}, f"human:{self.reviewer}"
