"""Human-in-the-loop approval for side-effecting tools."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


class ApprovalPolicy(Protocol):
    def approve(self, tool_name: str, tool_input: dict[str, Any]) -> bool: ...


@dataclass
class AutoDeny:
    """Default policy: nothing with side effects runs without a human."""

    asked: list[str] = field(default_factory=list)

    def approve(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        self.asked.append(tool_name)
        return False


@dataclass
class AutoApprove:
    """For trusted batch runs (``--yes``) and tests."""

    asked: list[str] = field(default_factory=list)

    def approve(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        self.asked.append(tool_name)
        return True


class ConsoleApproval:
    """Ask on the terminal. ``ask`` is injectable so tests can simulate the reviewer."""

    def __init__(
        self, ask: Callable[[str], str] = input, echo: Callable[[str], None] = print
    ) -> None:
        self.ask = ask
        self.echo = echo

    def approve(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        preview = json.dumps(tool_input, indent=2)[:800]
        self.echo(f"\n[approval needed] The agent wants to call {tool_name}:\n{preview}")
        answer = self.ask("Allow? [y/N] ").strip().lower()
        return answer in {"y", "yes"}
