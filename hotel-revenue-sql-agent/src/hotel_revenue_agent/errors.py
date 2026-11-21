"""Custom exception hierarchy. Every failure the agent can recover from is a ToolError."""

from __future__ import annotations


class AgentError(Exception):
    """Base class for all errors raised by this package."""


class ConfigError(AgentError):
    """Invalid or missing configuration."""


class ToolError(AgentError):
    """A tool call failed. The message is returned to the model so it can self-correct."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint

    def to_model_text(self) -> str:
        text = f"ERROR: {self}"
        if self.hint:
            text += f"\nHINT: {self.hint}"
        return text


class SQLGuardError(ToolError):
    """The SQL was rejected by the read-only guardrail before it reached the database."""


class ToolNotAllowedError(ToolError):
    """The model asked for a tool that is not on the allowlist."""


class ApprovalDeniedError(ToolError):
    """A human reviewer declined a side-effecting tool call."""


class BudgetExceededError(AgentError):
    """The run hit its step or token budget."""


class LLMError(AgentError):
    """The model provider returned something the agent cannot use (refusal, truncation)."""
