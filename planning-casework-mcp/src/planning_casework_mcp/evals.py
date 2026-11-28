"""Evaluation suite.

Part A, tool golden set: calls each MCP tool through the real protocol and compares with
answers worked out by hand from the fixtures (deadlines, routes, counts, refusals).
Part B, agent scenarios: runs the agent loop end to end and checks the trajectory (which
tools ran, what was blocked, what was approved, whether the answer is grounded).

Offline (CI) Part B uses ScriptedLLM, so it tests the harness rather than the model; with
--live the same tasks and checks run against Claude.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent.llm import LLMClient, ScriptedLLM
from .agent.loop import PlanningAgent
from .agent.mcp_bridge import MCPGateway, memory_gateway
from .agent.scenarios import Scenario, scenarios
from .config import Settings
from .datagen import TODAY, build_store

GoldenCheck = Callable[[bool, Any], bool]


@dataclass
class Golden:
    name: str
    tool: str
    args: dict[str, Any]
    expect: GoldenCheck
    why: str


def _ok(f: Callable[[Any], bool]) -> GoldenCheck:
    return lambda is_error, data: (not is_error) and f(data)


def _err(fragment: str) -> GoldenCheck:
    return lambda is_error, data: is_error and fragment in str(data)


APPROVE = {"recommendation": "approve"}

GOLDEN: list[Golden] = [
    Golden("householder 8-week date", "calculate_deadline", {"ref": "26/00417/HOU"},
           _ok(lambda d: d["statutory_date"] == "2026-11-19" and d["overdue"]),
           "validated 2026-09-24 + 8 weeks = 2026-11-19, past 'today' 2026-11-27"),
    Golden("publicity end", "calculate_deadline", {"ref": "26/00417/HOU"},
           _ok(lambda d: d["consultation_ends"] == "2026-10-17"
               and d["can_determine_from"] == "2026-10-18"),
           "site notice 2026-09-26 + 21 days"),
    Golden("major 13 weeks + extension", "calculate_deadline", {"ref": "26/00502/FUL"},
           _ok(lambda d: d["statutory_date"] == "2026-12-04"
               and d["effective_date"] == "2026-12-18" and not d["overdue"]),
           "2026-09-04 + 13 weeks; extension agreed to 2026-12-18"),
    Golden("prior approval 56 days", "calculate_deadline", {"ref": "26/00611/PA"},
           _ok(lambda d: d["statutory_date"] == "2026-11-30" and d["deemed_consent_risk"]
               and d["days_remaining"] == 3),
           "2026-10-05 + 56 days; deemed consent if missed"),
    Golden("not yet valid", "calculate_deadline", {"ref": "26/00701/HOU"},
           _ok(lambda d: d["clock_started"] is False and d["statutory_date"] is None),
           "the clock starts at validation"),
    Golden("decided case not overdue", "calculate_deadline", {"ref": "26/00288/FUL"},
           _ok(lambda d: d["overdue"] is False and d["days_remaining"] is None),
           "closed cases have no live deadline"),
    Golden("one household one objection", "summarise_consultations", {"ref": "26/00417/HOU"},
           _ok(lambda d: d["public_comments"]["objecting_addresses"] == 4
               and d["public_comments"]["duplicates_removed"] == 1),
           "12 Mill Lane submitted twice with different casing"),
    Golden("non-material issues separated", "summarise_consultations", {"ref": "26/00417/HOU"},
           _ok(lambda d: d["public_comments"]["material_objection_addresses"] == 3
               and "loss of private view (not material)" in d["public_comments"]["non_material"]),
           "loss of a view is not a planning matter"),
    Golden("injection comment flagged", "summarise_consultations", {"ref": "26/00417/HOU"},
           _ok(lambda d: d["comments_flagged_as_instructions"] == [900007]),
           "comment 900007 tells the AI to approve"),
    Golden("comment text off by default", "summarise_consultations", {"ref": "26/00417/HOU"},
           _ok(lambda d: "untrusted_public_comment_text" not in d),
           "raw public text only when asked for"),
    Golden("householder delegated", "recommend_route", {"ref": "26/00417/HOU", **APPROVE},
           _ok(lambda d: d["route"] == "delegated"), "3 material objectors < 5"),
    Golden("major to committee", "recommend_route", {"ref": "26/00502/FUL", **APPROVE},
           _ok(lambda d: d["route"] == "committee"), "majors always go to committee"),
    Golden("call-in to committee", "recommend_route", {"ref": "26/00390/COU", **APPROVE},
           _ok(lambda d: d["route"] == "committee"
               and any("called" in r for r in d["reasons"])), "councillor call-in"),
    Golden("staff applicant + objections", "recommend_route", {"ref": "26/00521/HOU", **APPROVE},
           _ok(lambda d: d["route"] == "committee" and len(d["reasons"]) == 2),
           "staff applicant, and 6 material objectors against approval"),
    Golden("objections irrelevant to refusal", "recommend_route",
           {"ref": "26/00521/HOU", "recommendation": "refuse"},
           _ok(lambda d: len(d["reasons"]) == 1), "the threshold applies to approvals only"),
    Golden("constraints bring policies", "check_constraints", {"ref": "26/00655/LBC"},
           _ok(lambda d: {c["kind"] for c in d["constraints"]}
               == {"listed_building", "conservation_area"}
               and [p["policy_id"] for p in d["relevant_policies"]] == ["DM1", "DM7"]),
           "listed building + conservation area -> DM7, DM1"),
    Golden("bad reference rejected", "get_application", {"ref": "26/417/HOU"},
           _err("not a valid reference"), "references are YY/NNNNN/TYPE"),
    Golden("unknown ward rejected", "search_applications", {"ward": "Atlantis"},
           _err("unknown ward"), "the error lists the real wards"),
    Golden("write without approver refused", "draft_decision_notice",
           {"ref": "26/00417/HOU", "recommendation": "approve", "reasons": [],
            "conditions": [], "idempotency_key": "golden-1"},
           _err("needs a human approver"), "approved_by is set only by the approval step"),
    Golden("refusal needs reasons", "draft_decision_notice",
           {"ref": "26/00417/HOU", "recommendation": "refuse", "reasons": [], "conditions": [],
            "idempotency_key": "golden-2", "approved_by": "Eval Officer"},
           _err("must give at least one reason"), "a refusal must cite policy"),
    Golden("publicity still running", "draft_decision_notice",
           {"ref": "26/00655/LBC", "recommendation": "approve", "reasons": [],
            "conditions": [], "idempotency_key": "golden-3", "approved_by": "Eval Officer"},
           _err("earliest decision date is 2026-12-05"), "2026-11-13 + 21 days, then +1"),
    Golden("committee item cannot be drafted", "draft_decision_notice",
           {"ref": "26/00390/COU", "recommendation": "approve", "reasons": [],
            "conditions": [], "idempotency_key": "golden-4", "approved_by": "Eval Officer"},
           _err("must go to planning committee"), "call-in"),
    Golden("approval gets time limit", "draft_decision_notice",
           {"ref": "26/00733/ADV", "recommendation": "approve", "reasons": [],
            "conditions": ["A1: Static illumination only."], "idempotency_key": "golden-5",
            "approved_by": "Eval Officer"},
           _ok(lambda d: d["created"]
               and d["draft"]["conditions"] == ["A1: Static illumination only."]),
           "advert consents have no TL01 condition"),
    Golden("idempotent retry", "draft_decision_notice",
           {"ref": "26/00733/ADV", "recommendation": "approve", "reasons": [],
            "conditions": ["A1: Static illumination only."], "idempotency_key": "golden-5",
            "approved_by": "Eval Officer"},
           _ok(lambda d: d["created"] is False), "same key returns the same draft"),
    Golden("extension must move the date later", "record_extension_of_time",
           {"ref": "26/00502/FUL", "new_date": "2026-12-10",
            "reason": "Applicant agreed to more time.", "approved_by": "Eval Officer"},
           _err("must be after the current deadline 2026-12-18"), "extensions only extend"),
]  # fmt: skip


@dataclass
class CaseResult:
    suite: str
    name: str
    passed: bool
    detail: str = ""


@dataclass
class EvalReport:
    results: list[CaseResult] = field(default_factory=list)

    def rate(self, suite: str | None = None) -> float:
        rs = [r for r in self.results if suite is None or r.suite == suite]
        return sum(r.passed for r in rs) / len(rs) if rs else 0.0

    def render(self) -> str:
        lines = []
        for suite in ("tools", "agent"):
            rs = [r for r in self.results if r.suite == suite]
            lines.append(
                f"{suite:6s} {sum(r.passed for r in rs):3d}/{len(rs):<3d} ({self.rate(suite):.0%})"
            )
        lines.append(f"total  {sum(r.passed for r in self.results):3d}/{len(self.results):<3d} "
                     f"({self.rate():.0%})")  # fmt: skip
        failures = [r for r in self.results if not r.passed]
        if failures:
            lines.append("failures:")
            lines += [f"  [{r.suite}] {r.name}: {r.detail}" for r in failures]
        return "\n".join(lines)


async def run_golden(gateway: MCPGateway) -> list[CaseResult]:
    out = []
    for g in GOLDEN:
        outcome = await gateway.call(g.tool, g.args)
        data = outcome.json() if not outcome.is_error else outcome.text
        passed = bool(g.expect(outcome.is_error, data))
        out.append(CaseResult("tools", g.name, passed, "" if passed else f"got {str(data)[:160]}"))
    return out


async def run_scenario(
    sc: Scenario, gateway: MCPGateway, settings: Settings, llm: LLMClient | None = None
):
    if sc.max_steps:
        settings = Settings(**{**settings.__dict__, "max_steps": sc.max_steps})
    agent = PlanningAgent(
        llm or ScriptedLLM(sc.script), gateway, sc.approver(), settings, sc.policy
    )
    return await agent.run(sc.task)


async def run_all(live_llm: Callable[[], LLMClient] | None = None) -> EvalReport:
    report = EvalReport()
    settings = Settings()
    with tempfile.TemporaryDirectory() as tmp:
        # Golden set and each scenario get a fresh database so writes never leak between cases.
        store = build_store(str(Path(tmp) / "golden.db"), n=200)
        async with memory_gateway(store, TODAY) as gw:
            report.results += await run_golden(gw)
        for i, sc in enumerate(scenarios()):
            store = build_store(str(Path(tmp) / f"s{i}.db"), n=200)
            async with memory_gateway(store, TODAY) as gw:
                result = await run_scenario(sc, gw, settings, live_llm() if live_llm else None)
            for label, check in sc.checks:
                problem = check(result)
                report.results.append(
                    CaseResult("agent", f"{sc.name}: {label}", problem is None, problem or "")
                )
    return report


def to_json(report: EvalReport) -> str:
    return json.dumps(
        {
            "tool_pass_rate": report.rate("tools"),
            "agent_pass_rate": report.rate("agent"),
            "overall_pass_rate": report.rate(),
            "cases": [r.__dict__ for r in report.results],
        },
        indent=2,
    )
