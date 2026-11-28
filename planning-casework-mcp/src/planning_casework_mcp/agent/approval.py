"""Human-in-the-loop approval for tools that change the casework record."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    approver: str
    note: str = ""


class Approver(Protocol):
    def decide(self, tool: str, args: dict[str, Any]) -> ApprovalDecision: ...


class ConsoleApprover:
    """Asks the person at the terminal. Anything other than 'y' is a refusal."""

    def __init__(
        self,
        name: str,
        ask: Callable[[str], str] = input,
        show: Callable[[str], None] = print,
    ) -> None:
        self.name = name
        self._ask = ask
        self._show = show

    def decide(self, tool: str, args: dict[str, Any]) -> ApprovalDecision:
        self._show(f"\n  APPROVAL NEEDED: {tool}\n  {json.dumps(args, indent=2)}")
        answer = self._ask("  Approve? [y/N] ").strip().lower()
        if answer == "y":
            return ApprovalDecision(True, self.name, "approved at the console")
        return ApprovalDecision(False, self.name, "declined at the console")


class AutoApprover:
    """For the offline demo and tests only: approves and says so in the trace."""

    def __init__(self, name: str = "demo approver") -> None:
        self.name = name

    def decide(self, tool: str, args: dict[str, Any]) -> ApprovalDecision:
        return ApprovalDecision(True, self.name, "auto-approved (demo)")


class DenyAll:
    def decide(self, tool: str, args: dict[str, Any]) -> ApprovalDecision:
        return ApprovalDecision(False, "policy", "writes are switched off for this run")


class ScriptedApprover:
    def __init__(self, answers: Sequence[bool], name: str = "test approver") -> None:
        self._answers = list(answers)
        self.name = name
        self.asked: list[tuple[str, dict[str, Any]]] = []

    def decide(self, tool: str, args: dict[str, Any]) -> ApprovalDecision:
        self.asked.append((tool, args))
        ok = self._answers.pop(0) if self._answers else False
        return ApprovalDecision(ok, self.name, "scripted yes" if ok else "scripted no")
