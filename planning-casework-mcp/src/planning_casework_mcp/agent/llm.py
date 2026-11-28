"""Model access behind a small protocol: the real Claude client and a deterministic script."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(RuntimeError):
    """The model call failed or refused."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str
    input_tokens: int
    output_tokens: int
    # Exactly what goes back into the conversation as the assistant turn. For Claude this is
    # the SDK's content list (thinking blocks included, unchanged), as the API requires.
    assistant_content: list[Any] = field(default_factory=list)


class LLMClient(Protocol):
    model: str

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse: ...


class ClaudeClient:
    """Claude via the official Anthropic SDK. Reads ANTHROPIC_API_KEY from the environment."""

    def __init__(self, model: str, max_tokens: int = 16000) -> None:
        import anthropic  # imported lazily so tests and demo never need the SDK configured

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMError("ANTHROPIC_API_KEY is not set; use --demo to run offline")
        self._client = anthropic.Anthropic()
        self._anthropic = anthropic
        self.model = model
        self.max_tokens = max_tokens
        self.use_fallbacks = os.environ.get("AGENT_FALLBACKS", "default") != "off"

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": messages,
            "tools": tools,
            "tool_choice": {"type": "auto"},
        }
        try:
            if self.use_fallbacks:
                # Server-side fallback: if the model declines, the API retries on a fallback
                # model chosen by refusal category (set AGENT_FALLBACKS=off to disable).
                response = self._client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"],
                    extra_body={"fallbacks": "default"},
                    **kwargs,
                )
            else:
                response = self._client.messages.create(**kwargs)
        except self._anthropic.RateLimitError as e:
            raise LLMError(f"rate limited: {e}") from e
        except self._anthropic.APIStatusError as e:
            raise LLMError(f"API error {e.status_code}: {e.message}") from e
        except self._anthropic.APIConnectionError as e:
            raise LLMError(f"connection failed: {e}") from e
        if response.stop_reason == "refusal":
            raise LLMError("the model declined this request")
        text = "".join(b.text for b in response.content if b.type == "text")
        calls = [
            ToolCall(b.id, b.name, dict(b.input)) for b in response.content if b.type == "tool_use"
        ]
        return LLMResponse(
            text=text,
            tool_calls=calls,
            stop_reason=response.stop_reason or "end_turn",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            assistant_content=list(response.content),
        )


# ---- deterministic scripted model -----------------------------------------------------------


@dataclass
class ScriptStep:
    text: str = ""
    calls: Sequence[tuple[str, dict[str, Any]]] = ()


Observations = list[dict[str, Any]]
StepFactory = Callable[[Observations], ScriptStep]
Step = ScriptStep | StepFactory


def _estimate_tokens(payload: Any) -> int:
    return max(1, len(json.dumps(payload, default=str)) // 4)


class ScriptedLLM:
    """Replays a fixed script of replies and tool calls. Steps can be functions of what the
    tools have returned so far, so a scripted final answer is built from real tool output.
    Token counts are estimates (4 characters per token) and are labelled as such."""

    model = "scripted"

    def __init__(self, steps: Sequence[Step]) -> None:
        self._steps = list(steps)
        self._i = 0
        self._call_seq = 0

    @property
    def exhausted(self) -> bool:
        return self._i >= len(self._steps)

    @staticmethod
    def observations(messages: list[dict[str, Any]]) -> Observations:
        """Every tool result so far as {name, is_error, data}, oldest first."""
        names: dict[str, str] = {}
        out: Observations = []
        for m in messages:
            content = m.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    names[block["id"]] = block["name"]
                elif block.get("type") == "tool_result":
                    raw = block.get("content", "")
                    try:
                        data: Any = json.loads(
                            raw.split("\n", 1)[-1] if raw.startswith("NOTE") else raw
                        )
                    except (json.JSONDecodeError, AttributeError):
                        data = raw
                    out.append(
                        {
                            "name": names.get(block["tool_use_id"], "?"),
                            "is_error": bool(block.get("is_error")),
                            "data": data,
                        }
                    )
        return out

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        if self.exhausted:
            step = ScriptStep(text="(script finished)")
        else:
            raw = self._steps[self._i]
            step = raw(self.observations(messages)) if callable(raw) else raw
            self._i += 1
        calls = []
        content: list[dict[str, Any]] = []
        if step.text:
            content.append({"type": "text", "text": step.text})
        for name, args in step.calls:
            self._call_seq += 1
            call = ToolCall(f"toolu_scripted_{self._call_seq:03d}", name, dict(args))
            calls.append(call)
            content.append({"type": "tool_use", "id": call.id, "name": name, "input": call.input})
        return LLMResponse(
            text=step.text,
            tool_calls=calls,
            stop_reason="tool_use" if calls else "end_turn",
            input_tokens=_estimate_tokens([system, messages, tools]),
            output_tokens=_estimate_tokens(content),
            assistant_content=content,
        )
