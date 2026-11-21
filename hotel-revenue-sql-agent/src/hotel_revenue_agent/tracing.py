"""Structured tracing: every LLM call and tool call becomes a span with latency and cost.

Spans are written as JSON Lines (one file per run) and can be rendered to a self-contained
HTML report. Logging uses the standard library with a JSON formatter.
"""

from __future__ import annotations

import html
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {"level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        data.update(getattr(record, "fields", {}))
        return json.dumps(data, default=str)


def configure_logging(level: str = "WARNING", json_logs: bool = False) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter() if json_logs else logging.Formatter("%(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger("hotel_revenue_agent")
    root.handlers[:] = [handler]
    root.setLevel(level)


@dataclass
class Span:
    run_id: str
    step: int
    kind: str  # "llm" | "tool" | "guardrail" | "approval"
    name: str
    started_at: float
    duration_ms: float = 0.0
    status: str = "ok"
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)


class Tracer:
    def __init__(self, price_per_mtok: tuple[float, float], run_id: str | None = None) -> None:
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.price_in, self.price_out = price_per_mtok
        self.spans: list[Span] = []
        self._log = logging.getLogger("hotel_revenue_agent.trace")

    def start(self, step: int, kind: str, name: str, **detail: Any) -> Span:
        span = Span(self.run_id, step, kind, name, time.perf_counter(), detail=dict(detail))
        self.spans.append(span)
        return span

    def end(
        self,
        span: Span,
        status: str = "ok",
        input_tokens: int = 0,
        output_tokens: int = 0,
        **detail: Any,
    ) -> Span:
        span.duration_ms = round((time.perf_counter() - span.started_at) * 1000, 2)
        span.status = status
        span.input_tokens, span.output_tokens = input_tokens, output_tokens
        span.cost_usd = round(
            input_tokens / 1e6 * self.price_in + output_tokens / 1e6 * self.price_out, 6
        )
        span.detail.update(detail)
        self._log.info(
            "span", extra={"fields": {k: v for k, v in asdict(span).items() if k != "detail"}}
        )
        return span

    # -- aggregates -------------------------------------------------------------------
    @property
    def total_tokens(self) -> int:
        return sum(s.input_tokens + s.output_tokens for s in self.spans)

    def summary(self) -> dict[str, Any]:
        llm = [s for s in self.spans if s.kind == "llm"]
        tools = [s for s in self.spans if s.kind == "tool"]
        return {
            "run_id": self.run_id,
            "llm_calls": len(llm),
            "tool_calls": len(tools),
            "tool_errors": sum(s.status != "ok" for s in tools),
            "input_tokens": sum(s.input_tokens for s in llm),
            "output_tokens": sum(s.output_tokens for s in llm),
            "cost_usd": round(sum(s.cost_usd for s in self.spans), 6),
            "llm_ms": round(sum(s.duration_ms for s in llm), 1),
            "tool_ms": round(sum(s.duration_ms for s in tools), 1),
        }

    def write_jsonl(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"run-{self.run_id}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for span in self.spans:
                fh.write(json.dumps(asdict(span), default=str) + "\n")
        return path


def load_spans(path: Path) -> list[Span]:
    return [Span(**json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def render_html(spans: list[Span], title: str = "Agent trace") -> str:
    """Self-contained HTML trace with a waterfall bar per span."""
    total = sum(s.duration_ms for s in spans) or 1.0
    rows = []
    for s in spans:
        width = max(1.0, 100 * s.duration_ms / total)
        colour = {"llm": "#4f6bed", "tool": "#2e9e6b"}.get(s.kind, "#c77d1a")
        if s.status != "ok":
            colour = "#c0392b"
        detail = html.escape(json.dumps(s.detail, default=str)[:400])
        rows.append(
            f"<tr><td>{s.step}</td><td>{s.kind}</td><td>{html.escape(s.name)}</td>"
            f"<td>{s.status}</td><td>{s.duration_ms:.1f}</td>"
            f"<td>{s.input_tokens}/{s.output_tokens}</td><td>${s.cost_usd:.5f}</td>"
            f"<td><div style='background:{colour};width:{width:.1f}%;height:10px'></div></td>"
            f"<td><code>{detail}</code></td></tr>"
        )
    cost = sum(s.cost_usd for s in spans)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;color:#222}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border-bottom:1px solid #ddd;padding:4px 6px;text-align:left;vertical-align:top}}
code{{font-size:11px;color:#555}}</style></head><body>
<h1>{html.escape(title)}</h1><p>{len(spans)} spans · {total:.0f} ms · est. cost ${cost:.4f}</p>
<table><tr><th>Step</th><th>Kind</th><th>Name</th><th>Status</th><th>ms</th>
<th>Tokens in/out</th><th>Cost</th><th style="width:20%">Waterfall</th><th>Detail</th></tr>
{"".join(rows)}</table></body></html>"""
