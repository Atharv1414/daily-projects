"""Model abstraction: a tiny protocol, the real Claude client and a deterministic ScriptedLLM.

The agent only ever sees ``LLMResponse`` objects whose ``content`` is a list of plain dicts in
the Messages API shape (``text`` and ``tool_use`` blocks). That keeps the loop testable and
lets the scripted model stand in for Claude without a network or an API key.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from hotel_revenue_agent.errors import ConfigError, LLMError

Block = dict[str, Any]
Message = dict[str, Any]


@dataclass
class LLMResponse:
    content: list[Block]
    stop_reason: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    estimated_usage: bool = False

    @property
    def text(self) -> str:
        return "\n".join(b["text"] for b in self.content if b.get("type") == "text").strip()

    @property
    def tool_calls(self) -> list[Block]:
        return [b for b in self.content if b.get("type") == "tool_use"]


class LLMClient(Protocol):
    model: str

    def complete(
        self, system: str, messages: Sequence[Message], tools: Sequence[dict[str, Any]]
    ) -> LLMResponse: ...


class ClaudeClient:
    """Calls Claude through the official SDK. Reads ANTHROPIC_API_KEY from the environment."""

    def __init__(self, model: str, max_tokens: int = 4_000) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ConfigError("ANTHROPIC_API_KEY is not set. Use --demo to run offline.")
        import anthropic  # imported lazily so tests and demo mode never need it configured

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(max_retries=3)
        self.model = model
        self.max_tokens = max_tokens

    def complete(
        self, system: str, messages: Sequence[Message], tools: Sequence[dict[str, Any]]
    ) -> LLMResponse:
        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=list(messages),
                tools=list(tools),
                output_config={"effort": "medium"},
                # Route refusals to a fallback model server-side instead of failing the run.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except self._anthropic.RateLimitError as exc:
            raise LLMError(f"Rate limited after retries: {exc}") from exc
        except self._anthropic.APIStatusError as exc:
            raise LLMError(f"API error {exc.status_code}: {exc.message}") from exc
        except self._anthropic.APIConnectionError as exc:
            raise LLMError(f"Could not reach the API: {exc}") from exc
        if response.stop_reason == "refusal":
            raise LLMError("The model declined this request.")
        content = [b.model_dump(mode="json", exclude_none=True) for b in response.content]
        return LLMResponse(
            content=content,
            stop_reason=response.stop_reason or "end_turn",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )


# --- Scripted model ---------------------------------------------------------------------


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]


@dataclass
class Turn:
    """One scripted model turn: optional text, plus tool calls OR a final answer.

    ``final`` may be a callable that receives the parsed payload of the most recent
    successful tool result, so a scripted answer can quote the real numbers from the DB.
    """

    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    final: str | Callable[[dict[str, Any] | None], str] | None = None


def last_tool_payload(messages: Sequence[Message]) -> dict[str, Any] | None:
    """Return the JSON payload of the newest non-error tool_result, if any."""
    for message in reversed(messages):
        if message["role"] != "user" or not isinstance(message["content"], list):
            continue
        for block in reversed(message["content"]):
            if block.get("type") == "tool_result" and not block.get("is_error"):
                try:
                    payload = json.loads(block["content"])
                except (TypeError, json.JSONDecodeError):
                    continue
                return payload.get("result", payload)
    return None


def _estimate_tokens(obj: Any) -> int:
    return max(1, len(json.dumps(obj, default=str)) // 4)


class ScriptedLLM:
    """Deterministic stand-in for Claude that replays a list of turns.

    Token usage is estimated (~4 characters per token) so traces and cost reports still
    show realistic shapes in demo mode; these numbers are flagged as estimates.
    """

    def __init__(self, turns: Sequence[Turn], model: str = "scripted") -> None:
        self.turns = list(turns)
        self.model = model
        self.calls = 0

    def complete(
        self, system: str, messages: Sequence[Message], tools: Sequence[dict[str, Any]]
    ) -> LLMResponse:
        if self.calls >= len(self.turns):
            raise LLMError("ScriptedLLM ran out of scripted turns.")
        turn = self.turns[self.calls]
        self.calls += 1
        content: list[Block] = []
        if turn.text:
            content.append({"type": "text", "text": turn.text})
        if turn.calls:
            for i, call in enumerate(turn.calls):
                content.append(
                    {
                        "type": "tool_use",
                        "id": f"toolu_{self.calls:02d}_{i}",
                        "name": call.name,
                        "input": call.input,
                    }
                )
            stop = "tool_use"
        else:
            final = (
                turn.final(last_tool_payload(messages))
                if callable(turn.final)
                else (turn.final or "")
            )
            content.append({"type": "text", "text": final})
            stop = "end_turn"
        return LLMResponse(
            content=content,
            stop_reason=stop,
            input_tokens=_estimate_tokens([system, list(messages), list(tools)]),
            output_tokens=_estimate_tokens(content),
            model=self.model,
            estimated_usage=True,
        )
