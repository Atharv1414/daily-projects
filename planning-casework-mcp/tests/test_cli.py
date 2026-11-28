"""End to end over real stdio: the CLI starts the server as a subprocess."""

from planning_casework_mcp.cli import main


def test_demo_over_stdio(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("PLANNING_SEED_SIZE", "200")
    assert main(["demo", "--trace-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "offline demo mode" in out
    assert "draft_decision_notice" in out and "answer check: grounded" in out
    html = (tmp_path / "demo-trace.html").read_text()
    assert "Agent trace" in html and "estimated" in html
    assert (tmp_path / "demo-trace.jsonl").read_text().count("\n") >= 8


def test_ask_without_key_exits_cleanly(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["ask", "hello"]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
