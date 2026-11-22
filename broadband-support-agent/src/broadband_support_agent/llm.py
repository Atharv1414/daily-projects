"""Model abstraction: a small protocol, the real Claude client and a deterministic ScriptedLLM.

The agent only sees ``LLMResponse`` objects whose ``content`` is a list of plain dicts in the
Messages API shape (``text`` / ``tool_use`` blocks, plus any ``thinking`` blocks, which are
passed back unchanged). Tests and ``--demo`` use ScriptedLLM: no network, no API key.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from broadband_support_agent.errors import ConfigError, LLMError

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
    """Calls Claude with the official SDK. Reads ANTHROPIC_API_KEY from the environment."""

    def __init__(self, model: str, max_tokens: int = 16_000) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ConfigError("ANTHROPIC_API_KEY is not set. Use --demo to run offline.")
        import anthropic  # lazy import: demo mode and tests never touch the SDK client

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
                # Route safety-classifier refusals to a fallback model server-side.
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


Payloads = list[dict[str, Any]]


@dataclass
class ToolCall:
    """A scripted tool call. ``input`` may be a callable over earlier tool payloads, so a
    script can, for example, book the first free slot that list_engineer_slots returned."""

    name: str
    input: dict[str, Any] | Callable[[Payloads], dict[str, Any]]


@dataclass
class Turn:
    """One scripted model turn: optional text plus tool calls, OR a final answer.

    ``final`` may be a callable receiving every successful tool payload so far (oldest
    first), so a scripted reply can quote real numbers from the database.
    """

    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    final: str | Callable[[Payloads], str] | None = None


def tool_payloads(messages: Sequence[Message]) -> Payloads:
    out: Payloads = []
    for message in messages:
        if message["role"] != "user" or not isinstance(message["content"], list):
            continue
        for block in message["content"]:
            if block.get("type") != "tool_result" or block.get("is_error"):
                continue
            try:
                payload = json.loads(block["content"])
            except (TypeError, json.JSONDecodeError):
                continue
            out.append(payload.get("result", payload))
    return out


def _estimate_tokens(obj: Any) -> int:
    return max(1, len(json.dumps(obj, default=str)) // 4)


class ScriptedLLM:
    """Deterministic stand-in for Claude that replays a list of turns.

    Token usage is estimated (~4 characters per token) so traces and cost reports keep
    realistic shapes in demo mode; these numbers are flagged as estimates.
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
            payloads = tool_payloads(messages)
            for i, call in enumerate(turn.calls):
                call_input = call.input(payloads) if callable(call.input) else call.input
                content.append(
                    {
                        "type": "tool_use",
                        "id": f"toolu_{self.calls:02d}_{i}",
                        "name": call.name,
                        "input": call_input,
                    }
                )
            stop = "tool_use"
        else:
            final = turn.final(tool_payloads(messages)) if callable(turn.final) else turn.final
            content.append({"type": "text", "text": final or ""})
            stop = "end_turn"
        return LLMResponse(
            content=content,
            stop_reason=stop,
            input_tokens=_estimate_tokens([system, list(messages), list(tools)]),
            output_tokens=_estimate_tokens(content),
            model=self.model,
            estimated_usage=True,
        )
