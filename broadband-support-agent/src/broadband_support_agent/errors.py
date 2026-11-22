"""Custom exceptions. Tool errors carry a hint so the model can self-correct."""

from __future__ import annotations

import json


class SupportAgentError(Exception):
    """Base class for every error raised by this package."""


class ConfigError(SupportAgentError):
    """Missing or invalid configuration (for example no API key in live mode)."""


class LLMError(SupportAgentError):
    """The model call failed or returned something unusable."""


class BudgetExceededError(SupportAgentError):
    """A step, token or error budget was exhausted."""


class ToolError(SupportAgentError):
    """A tool failed. The message and hint are returned to the model as an error result."""

    code = "tool_error"

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint

    def to_model_text(self) -> str:
        payload = {"error": self.code, "message": str(self)}
        if self.hint:
            payload["hint"] = self.hint
        return json.dumps(payload)


class UnknownToolError(ToolError):
    code = "unknown_tool"


class ToolValidationError(ToolError):
    code = "invalid_input"


class NotFoundError(ToolError):
    code = "not_found"


class PolicyViolationError(ToolError):
    """A business rule forbids the action (for example a credit above the hard limit)."""

    code = "policy_violation"


class VerificationRequiredError(PolicyViolationError):
    code = "verification_required"


class ApprovalDeniedError(ToolError):
    code = "approval_denied"


class ConflictError(ToolError):
    """Optimistic-concurrency failure, e.g. an engineer slot booked by someone else."""

    code = "conflict"
