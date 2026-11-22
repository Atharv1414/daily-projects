from __future__ import annotations

import json

import pytest

from broadband_support_agent.agent import SupportAgent
from broadband_support_agent.approval import AutoDeny
from broadband_support_agent.config import Settings
from broadband_support_agent.errors import LLMError
from broadband_support_agent.llm import LLMResponse, ScriptedLLM, ToolCall, Turn, tool_payloads
from broadband_support_agent.tools import build_registry


def agent(repo, turns, settings=None, approval=None):
    return SupportAgent(
        ScriptedLLM(turns), build_registry(), repo, settings or Settings(), approval or AutoDeny()
    )


def test_happy_path_returns_answer_and_trace(repo):
    turns = [
        Turn(
            calls=[ToolCall("verify_customer", {"account_id": "NW-100007", "postcode": "NG7 2RD"})]
        ),
        Turn(final="You're verified."),
    ]
    result = agent(repo, turns).run("hello")
    assert result.status == "resolved" and result.answer == "You're verified."
    assert result.trace["llm_calls"] == 2 and result.trace["tool_calls"] == 1
    assert result.trace["estimated_usage"] and result.trace["cost_usd"] > 0


def test_parallel_tool_calls_return_in_one_user_message(repo):
    seen = {}

    class Spy(ScriptedLLM):
        def complete(self, system, messages, tools):
            seen["messages"] = list(messages)
            return super().complete(system, messages, tools)

    turns = [
        Turn(
            calls=[
                ToolCall("search_help_articles", {"query": "wifi slow"}),
                ToolCall("search_help_articles", {"query": "restart hub"}),
            ]
        ),
        Turn(final="done"),
    ]
    SupportAgent(Spy(turns), build_registry(), repo, Settings(), AutoDeny()).run("help")
    results_msg = seen["messages"][-1]
    assert results_msg["role"] == "user" and len(results_msg["content"]) == 2


def test_tool_results_are_wrapped_as_untrusted(repo):
    turns = [
        Turn(calls=[ToolCall("search_help_articles", {"query": "wifi"})]),
        Turn(final=lambda p: str(len(p))),
    ]
    result = agent(repo, turns).run("wifi")
    assert result.answer == "1"


def test_llm_error_is_contained(repo):
    result = agent(repo, []).run("hi")
    assert result.status == "error" and "model error" in result.answer


def test_max_tokens_stop_reason_is_an_error(repo):
    class Truncating:
        model = "scripted"

        def complete(self, system, messages, tools):
            return LLMResponse([{"type": "text", "text": "partial"}], "max_tokens")

    result = SupportAgent(Truncating(), build_registry(), repo, Settings()).run("hi")
    assert result.status == "error"


def test_token_budget(repo):
    turns = [Turn(calls=[ToolCall("search_help_articles", {"query": "router"})])] * 5
    result = agent(repo, turns, Settings(max_total_tokens=500)).run("hi")
    assert result.status == "budget_exceeded" and "Token budget" in result.answer


def test_empty_message_rejected(repo):
    with pytest.raises(ValueError):
        agent(repo, []).run("   ")


def test_card_number_never_reaches_model(repo):
    seen = {}

    class Spy(ScriptedLLM):
        def complete(self, system, messages, tools):
            seen["first"] = messages[0]["content"]
            return super().complete(system, messages, tools)

    SupportAgent(Spy([Turn(final="ok")]), build_registry(), repo, Settings()).run(
        "pay with 4111 1111 1111 1111"
    )
    assert "4111 1111 1111 1111" not in seen["first"] and "****1111" in seen["first"]


def test_tool_payloads_skips_errors():
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "content": json.dumps({"result": {"a": 1}}),
                    "is_error": False,
                },
                {"type": "tool_result", "content": '{"error": "x"}', "is_error": True},
            ],
        }
    ]
    assert tool_payloads(messages) == [{"a": 1}]


def test_scripted_llm_runs_out():
    llm = ScriptedLLM([])
    with pytest.raises(LLMError):
        llm.complete("", [], [])
