import sqlite3

import pytest

from hotel_revenue_agent.config import Settings
from hotel_revenue_agent.datagen import generate
from hotel_revenue_agent.errors import ConfigError
from hotel_revenue_agent.llm import ClaudeClient, ScriptedLLM, ToolCall, Turn, last_tool_payload
from hotel_revenue_agent.tools import result_block
from hotel_revenue_agent.tracing import load_spans, render_html


def test_claude_client_requires_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="--demo"):
        ClaudeClient("claude-sonnet-5-5")


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "claude-opus-5-5")
    monkeypatch.setenv("AGENT_MAX_STEPS", "4")
    s = Settings.from_env()
    assert s.model == "claude-opus-5-5" and s.max_steps == 4
    assert s.price() == (4.0, 20.0)


@pytest.mark.parametrize("value", ["zero", "0"])
def test_settings_reject_bad_ints(monkeypatch, value):
    monkeypatch.setenv("AGENT_MAX_STEPS", value)
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_scripted_llm_emits_tool_use_blocks():
    llm = ScriptedLLM([Turn(text="checking", calls=[ToolCall("list_tables", {})])])
    resp = llm.complete("sys", [{"role": "user", "content": "q"}], [])
    assert resp.stop_reason == "tool_use" and resp.tool_calls[0]["name"] == "list_tables"
    assert resp.estimated_usage and resp.input_tokens > 0


def test_last_tool_payload_skips_errors():
    messages = [
        {"role": "user", "content": [result_block("a", {"rows": [[1]]})]},
        {"role": "assistant", "content": []},
        {"role": "user", "content": [result_block("b", "ERROR", is_error=True)]},
    ]
    assert last_tool_payload(messages) == {"rows": [[1]]}


def test_generator_is_deterministic(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    assert generate(a, bookings=500, guests=100, seed=3) == generate(
        b, bookings=500, guests=100, seed=3
    )
    q = "SELECT SUM(nightly_rate_gbp), COUNT(DISTINCT status) FROM bookings"
    ra = sqlite3.connect(a).execute(q).fetchone()
    assert ra == sqlite3.connect(b).execute(q).fetchone()
    assert ra[1] == 3


def test_generated_data_is_messy_but_valid(db_path):
    con = sqlite3.connect(db_path)
    nulls = con.execute("SELECT COUNT(*) FROM bookings WHERE channel IS NULL").fetchone()[0]
    orphan = con.execute(
        "SELECT COUNT(*) FROM ancillary_charges a LEFT JOIN bookings b "
        "USING (booking_id) WHERE b.status <> 'completed'"
    ).fetchone()[0]
    assert nulls > 0 and orphan == 0


def test_trace_html_renders(tmp_path, registry, settings):
    from hotel_revenue_agent.agent import AnalystAgent

    agent = AnalystAgent(
        ScriptedLLM([Turn(calls=[ToolCall("list_tables", {})]), Turn(final="ok")]),
        registry,
        settings,
    )
    agent.run("q")
    page = render_html(load_spans(agent.tracer.write_jsonl(tmp_path)))
    assert "<table>" in page and "list_tables" in page
