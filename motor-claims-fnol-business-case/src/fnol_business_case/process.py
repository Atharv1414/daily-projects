"""Process maps: current vs future state, lean metrics and Mermaid swimlane rendering."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Step:
    id: str
    name: str
    lane: str
    work_min: float
    wait_min: float
    value_add: bool


@dataclass(frozen=True)
class Process:
    title: str
    steps: list[Step]
    flows: list[list[str]]
    simple_share: float | None = None

    def step(self, sid: str) -> Step:
        return next(s for s in self.steps if s.id == sid)


@dataclass(frozen=True)
class ProcessMetrics:
    lead_time_hours: float
    touch_time_min: float
    value_add_min: float
    process_cycle_efficiency: float
    handoffs: float
    steps: int


def load(path: Path) -> dict[str, Process]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        k: Process(v["title"], [Step(**s) for s in v["steps"]], v["flows"], v.get("simple_share"))
        for k, v in raw.items()
    }


def _paths(p: Process) -> list[tuple[list[str], float]]:
    """All start-to-end paths with their probability (branches labelled simple/complex)."""
    out_edges: dict[str, list[list[str]]] = {}
    for f in p.flows:
        out_edges.setdefault(f[0], []).append(f)
    targets = {f[1] for f in p.flows}
    start = next(s.id for s in p.steps if s.id not in targets)

    def walk(node: str, prob: float, path: list[str]) -> list[tuple[list[str], float]]:
        edges = out_edges.get(node, [])
        if not edges:
            return [(path, prob)]
        res = []
        for e in edges:
            w = 1.0
            if len(edges) > 1:
                share = p.simple_share if p.simple_share is not None else 1 / len(edges)
                w = share if "simple" in (e[2] if len(e) > 2 else "") else 1 - share
            res += walk(e[1], prob * w, path + [e[1]])
        return res

    return walk(start, 1.0, [start])


def metrics(p: Process) -> ProcessMetrics:
    """Expected lead time, touch time, PCE and handoffs, weighting branches by probability."""
    lead = touch = va = handoffs = 0.0
    for path, prob in _paths(p):
        steps = [p.step(s) for s in path]
        lead += prob * sum(s.work_min + s.wait_min for s in steps)
        touch += prob * sum(s.work_min for s in steps)
        va += prob * sum(s.work_min for s in steps if s.value_add)
        handoffs += prob * sum(a.lane != b.lane for a, b in zip(steps, steps[1:], strict=False))
    return ProcessMetrics(
        round(lead / 60, 1),
        round(touch, 1),
        round(va, 1),
        round(va / lead, 4) if lead else 0.0,
        round(handoffs, 2),
        len(p.steps),
    )


def mermaid(p: Process) -> str:
    lines = ["flowchart LR"]
    lanes: dict[str, list[Step]] = {}
    for s in p.steps:
        lanes.setdefault(s.lane, []).append(s)
    for i, (lane, steps) in enumerate(lanes.items()):
        lines.append(f'  subgraph L{i}["{lane}"]')
        for s in steps:
            wait = f"<br/>wait {s.wait_min / 60:.0f}h" if s.wait_min >= 60 else ""
            cls = "" if s.value_add else ":::nva"
            lines.append(f'    {s.id}["{s.name}<br/>{s.work_min:g} min{wait}"]{cls}')
        lines.append("  end")
    for f in p.flows:
        label = f"|{f[2]}|" if len(f) > 2 else ""
        lines.append(f"  {f[0]} -->{label} {f[1]}")
    lines.append("  classDef nva fill:#fde2e1,stroke:#c23934")
    return "\n".join(lines)
