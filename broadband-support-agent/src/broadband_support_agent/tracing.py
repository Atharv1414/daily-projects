"""Tracing: a span per model call, tool call and guardrail event, with tokens, cost and latency.

Traces are written as JSON lines and can be rendered as a self-contained HTML report.
Everything passes through PII redaction before it is stored.
"""

from __future__ import annotations

import html
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from broadband_support_agent.guardrails import redact_pii


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        payload.update(getattr(record, "fields", {}))
        return redact_pii(json.dumps(payload, default=str))


def configure_logging(level: str = "WARNING") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("broadband_support_agent")
    root.handlers[:] = [handler]
    root.setLevel(level)


@dataclass
class Span:
    step: int
    kind: str  # "llm" | "tool" | "guardrail" | "approval"
    name: str
    started: float
    duration_ms: float = 0.0
    status: str = "ok"
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    attrs: dict[str, Any] = field(default_factory=dict)


class Tracer:
    def __init__(self, price_per_mtok: tuple[float, float]) -> None:
        self.price_in, self.price_out = price_per_mtok
        self.spans: list[Span] = []
        self._t0 = time.perf_counter()

    def start(self, step: int, kind: str, name: str, **attrs: Any) -> Span:
        span = Span(step, kind, name, time.perf_counter(), attrs=_clean(attrs))
        self.spans.append(span)
        return span

    def end(self, span: Span, status: str = "ok", **attrs: Any) -> None:
        span.duration_ms = round((time.perf_counter() - span.started) * 1000, 3)
        span.status = status
        span.input_tokens = int(attrs.pop("input_tokens", 0) or 0)
        span.output_tokens = int(attrs.pop("output_tokens", 0) or 0)
        span.cost_usd = round(
            span.input_tokens * self.price_in / 1e6 + span.output_tokens * self.price_out / 1e6, 6
        )
        span.attrs.update(_clean(attrs))

    def event(self, step: int, kind: str, name: str, status: str, **attrs: Any) -> None:
        span = self.start(step, kind, name, **attrs)
        self.end(span, status=status)

    @property
    def total_tokens(self) -> int:
        return sum(s.input_tokens + s.output_tokens for s in self.spans)

    def summary(self) -> dict[str, Any]:
        llm = [s for s in self.spans if s.kind == "llm"]
        tools = [s for s in self.spans if s.kind == "tool"]
        return {
            "llm_calls": len(llm),
            "tool_calls": len(tools),
            "tool_errors": sum(s.status != "ok" for s in tools),
            "input_tokens": sum(s.input_tokens for s in llm),
            "output_tokens": sum(s.output_tokens for s in llm),
            "cost_usd": round(sum(s.cost_usd for s in llm), 5),
            "wall_ms": round((time.perf_counter() - self._t0) * 1000, 2),
            "estimated_usage": any(s.attrs.get("estimated_usage") for s in llm),
        }

    def to_records(self) -> list[dict[str, Any]]:
        out = []
        for s in self.spans:
            rec = asdict(s)
            rec.pop("started")
            out.append(rec)
        return out

    def write_jsonl(self, path: Path, session_id: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for rec in self.to_records():
                fh.write(redact_pii(json.dumps({"session": session_id, **rec}, default=str)))
                fh.write("\n")


def _clean(attrs: dict[str, Any]) -> dict[str, Any]:
    return json.loads(redact_pii(json.dumps(attrs, default=str)))


STATUS_COLOUR = {
    "ok": "#1a7f37",
    "error": "#cf222e",
    "blocked": "#9a6700",
    "denied": "#9a6700",
    "flagged": "#9a6700",
    "approved": "#1a7f37",
}


def render_html(sessions: list[dict[str, Any]], title: str = "Support agent traces") -> str:
    """Render one or more sessions (each with question, status, trace and spans) as HTML."""
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>{html.escape(title)}</title><style>",
        "body{font-family:system-ui,sans-serif;margin:24px;color:#1f2328;background:#fff}",
        "table{border-collapse:collapse;width:100%;margin:8px 0 24px;font-size:13px}",
        "td,th{border:1px solid #d0d7de;padding:4px 8px;text-align:left;vertical-align:top}",
        "th{background:#f6f8fa}.pill{padding:1px 8px;border-radius:10px;color:#fff}",
        ".bar{background:#0969da;height:8px;border-radius:4px}code{font-size:12px}",
        "</style></head><body>",
        f"<h1>{html.escape(title)}</h1>",
    ]
    for sess in sessions:
        summary = sess["trace"]
        parts.append(f"<h2>{html.escape(sess['name'])}</h2>")
        parts.append(
            f"<p><b>Status:</b> {html.escape(sess['status'])} · <b>LLM calls:</b> "
            f"{summary['llm_calls']} · <b>tool calls:</b> {summary['tool_calls']} · "
            f"<b>tokens:</b> {summary['input_tokens'] + summary['output_tokens']:,}"
            f"{' (estimated)' if summary['estimated_usage'] else ''} · <b>cost:</b> "
            f"${summary['cost_usd']:.4f}</p>"
        )
        longest = max((s["duration_ms"] for s in sess["spans"]), default=1) or 1
        parts.append(
            "<table><tr><th>Step</th><th>Kind</th><th>Name</th><th>Status</th>"
            "<th>Latency</th><th>Tokens</th><th>Details</th></tr>"
        )
        for s in sess["spans"]:
            colour = STATUS_COLOUR.get(s["status"], "#57606a")
            width = max(2, int(120 * s["duration_ms"] / longest))
            details = html.escape(json.dumps(s["attrs"], default=str)[:300])
            parts.append(
                f"<tr><td>{s['step']}</td><td>{s['kind']}</td><td>{html.escape(s['name'])}</td>"
                f"<td><span class='pill' style='background:{colour}'>{s['status']}</span></td>"
                f"<td><div class='bar' style='width:{width}px'></div>{s['duration_ms']:.2f} ms"
                f"</td><td>{s['input_tokens'] + s['output_tokens'] or ''}</td>"
                f"<td><code>{details}</code></td></tr>"
            )
        parts.append("</table>")
    parts.append("</body></html>")
    return "".join(parts)
