"""Step-by-step tracing of agent runs: model calls, tool calls, approvals, guardrail events,
with latency, tokens and estimated cost. Exported as JSON lines and an HTML report."""

from __future__ import annotations

import html
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Span:
    kind: str  # llm, tool, approval, guardrail
    name: str
    step: int
    started: float
    latency_ms: float = 0.0
    ok: bool = True
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)


class Tracer:
    def __init__(self, input_price: float = 2.0, output_price: float = 10.0) -> None:
        self.spans: list[Span] = []
        self._t0 = time.perf_counter()
        self.input_price = input_price
        self.output_price = output_price
        self.token_counts_estimated = False

    def start(self) -> float:
        return time.perf_counter()

    def llm(self, step: int, started: float, model: str, inp: int, out: int, stop: str) -> Span:
        cost = inp / 1e6 * self.input_price + out / 1e6 * self.output_price
        span = Span(
            "llm",
            model,
            step,
            started - self._t0,
            (time.perf_counter() - started) * 1000,
            True,
            inp,
            out,
            cost,
            {"stop_reason": stop},
        )
        self.spans.append(span)
        return span

    def tool(self, step: int, started: float, name: str, ok: bool, **detail: Any) -> Span:
        span = Span(
            "tool",
            name,
            step,
            started - self._t0,
            (time.perf_counter() - started) * 1000,
            ok,
            detail=detail,
        )
        self.spans.append(span)
        return span

    def event(self, kind: str, step: int, name: str, ok: bool = True, **detail: Any) -> Span:
        span = Span(kind, name, step, time.perf_counter() - self._t0, ok=ok, detail=detail)
        self.spans.append(span)
        return span

    # ---- summaries -----------------------------------------------------------------------

    def totals(self) -> dict[str, Any]:
        llm = [s for s in self.spans if s.kind == "llm"]
        tools = [s for s in self.spans if s.kind == "tool"]
        return {
            "model_calls": len(llm),
            "tool_calls": len(tools),
            "tool_errors": sum(not s.ok for s in tools),
            "input_tokens": sum(s.input_tokens for s in llm),
            "output_tokens": sum(s.output_tokens for s in llm),
            "cost_usd": round(sum(s.cost_usd for s in llm), 5),
            "model_latency_ms": round(sum(s.latency_ms for s in llm), 1),
            "tool_latency_ms": round(sum(s.latency_ms for s in tools), 1),
            "guardrail_events": sum(s.kind == "guardrail" for s in self.spans),
            "approvals": sum(s.kind == "approval" for s in self.spans),
            "tokens_estimated": self.token_counts_estimated,
        }

    def to_jsonl(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for s in self.spans:
                f.write(json.dumps(asdict(s), default=str) + "\n")

    def to_html(self, path: str | Path, title: str, final_answer: str) -> None:
        t = self.totals()
        total_ms = max(1.0, max((s.started * 1000 + s.latency_ms for s in self.spans), default=1))
        colours = {
            "llm": "#3559a8",
            "tool": "#2f7d5b",
            "approval": "#a86a00",
            "guardrail": "#b3261e",
        }
        rows = []
        for s in self.spans:
            left = s.started * 1000 / total_ms * 100
            width = max(0.6, s.latency_ms / total_ms * 100)
            detail = html.escape(json.dumps(s.detail, default=str)[:300])
            tokens = f"{s.input_tokens}/{s.output_tokens}" if s.kind == "llm" else ""
            rows.append(
                f"<tr><td>{s.step}</td><td><span class='k' style='background:{colours[s.kind]}'>"
                f"{s.kind}</span></td><td>{html.escape(s.name)}</td>"
                f"<td>{'ok' if s.ok else '<b>error</b>'}</td><td>{s.latency_ms:.1f}</td>"
                f"<td>{tokens}</td><td class='bar'><div style='margin-left:{left:.2f}%;"
                f"width:{width:.2f}%;background:{colours[s.kind]}'></div></td>"
                f"<td class='d'>{detail}</td></tr>"
            )
        est = " (estimated: scripted model)" if t["tokens_estimated"] else ""
        doc = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body{{font:14px/1.45 system-ui,sans-serif;margin:2rem;color:#1d1d1f;max-width:1200px}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:4px 6px;
text-align:left;vertical-align:top}}
.k{{color:#fff;border-radius:3px;padding:1px 6px;font-size:12px}}
.bar{{width:24%}}.bar div{{height:10px;border-radius:2px}}.d{{font:12px ui-monospace,monospace;
color:#555;word-break:break-all}}
dl{{display:grid;grid-template-columns:repeat(4,auto);gap:4px 18px}}
dt{{color:#666}}pre{{white-space:pre-wrap;background:#f4f4f6;padding:1rem;border-radius:6px}}
</style><h1>{html.escape(title)}</h1><dl>
<dt>model calls</dt><dd>{t["model_calls"]}</dd><dt>tool calls</dt><dd>{t["tool_calls"]}
({t["tool_errors"]} errors)</dd><dt>tokens in/out{est}</dt><dd>{t["input_tokens"]} /
{t["output_tokens"]}</dd><dt>cost (USD){est}</dt><dd>{t["cost_usd"]:.4f}</dd>
<dt>model latency</dt><dd>{t["model_latency_ms"]} ms</dd><dt>tool latency</dt>
<dd>{t["tool_latency_ms"]} ms</dd><dt>guardrail events</dt><dd>{t["guardrail_events"]}</dd>
<dt>approvals</dt><dd>{t["approvals"]}</dd></dl>
<table><tr><th>step</th><th>kind</th><th>name</th><th>result</th><th>ms</th><th>tokens</th>
<th>timeline</th><th>detail</th></tr>{"".join(rows)}</table>
<h2>Final answer</h2><pre>{html.escape(final_answer)}</pre></html>"""
        Path(path).write_text(doc, encoding="utf-8")
