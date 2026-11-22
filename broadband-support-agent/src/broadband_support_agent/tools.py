"""The agent's tools: validated Pydantic inputs, an allowlist registry and handlers.

Every tool result goes back to the model wrapped as untrusted data. Side-effecting tools
(credits, bookings) run policy checks and, where required, ask a human before writing.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from broadband_support_agent import policy
from broadband_support_agent.approval import ApprovalPolicy, ApprovalRequest
from broadband_support_agent.config import Settings
from broadband_support_agent.database import Repository
from broadband_support_agent.errors import (
    ApprovalDeniedError,
    ConflictError,
    NotFoundError,
    PolicyViolationError,
    ToolValidationError,
    UnknownToolError,
)
from broadband_support_agent.guardrails import neutralise
from broadband_support_agent.state import Handoff, SessionState
from broadband_support_agent.tracing import Tracer

log = logging.getLogger("broadband_support_agent.tools")

ACCOUNT_RE = r"^NW-\d{6}$"
MAX_VERIFY_ATTEMPTS = 3


def normalise_postcode(raw: str) -> str:
    return re.sub(r"\s+", "", raw).upper()


# --- input schemas ----------------------------------------------------------------------


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AccountInput(StrictModel):
    account_id: str = Field(pattern=ACCOUNT_RE, description="Account number, e.g. NW-100001")


class VerifyInput(AccountInput):
    postcode: str = Field(min_length=5, max_length=9, description="Billing postcode")

    @field_validator("postcode")
    @classmethod
    def looks_like_uk_postcode(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z]{1,2}\d[A-Za-z\d]?\s*\d[A-Za-z]{2}", v):
            raise ValueError("not a UK postcode")
        return v


class BillingInput(AccountInput):
    months: int = Field(default=3, ge=1, le=12)


class SearchInput(StrictModel):
    query: str = Field(min_length=3, max_length=200)


class CreditInput(AccountInput):
    amount_gbp: float = Field(gt=0, le=1000, description="Credit amount in GBP")
    category: Literal["billing_error", "goodwill"]
    reason: str = Field(min_length=5, max_length=200)
    invoice_id: str | None = Field(
        default=None, description="Required for billing_error: the duplicated invoice line"
    )


class BookInput(AccountInput):
    slot_id: str = Field(pattern=r"^SL-[A-Z]{3}-\d{4}-(AM|PM)$")


class EscalateInput(StrictModel):
    account_id: str | None = Field(default=None, pattern=ACCOUNT_RE)
    category: Literal["retention", "billing", "fault", "priority_care", "complaint", "other"]
    summary: str = Field(min_length=10, max_length=500)


# --- registry ---------------------------------------------------------------------------


@dataclass
class ToolContext:
    repo: Repository
    settings: Settings
    state: SessionState
    approval: ApprovalPolicy
    tracer: Tracer
    step: int = 0

    @property
    def now(self) -> datetime:
        return self.settings.now


Handler = Callable[[ToolContext, Any], dict[str, Any]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: type[StrictModel]
    handler: Handler
    side_effect: bool = False

    def spec(self) -> dict[str, Any]:
        schema = self.schema.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        return {"name": self.name, "description": self.description, "input_schema": schema}


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {t.name: t for t in tools}

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[dict[str, Any]]:
        return [t.spec() for t in self._tools.values()]

    def validate(self, name: str, raw: Any) -> tuple[Tool, StrictModel]:
        tool = self._tools.get(name)
        if tool is None:
            raise UnknownToolError(
                f"Tool {name!r} is not on the allowlist.",
                hint=f"Available: {', '.join(self.names)}",
            )
        try:
            return tool, tool.schema.model_validate(raw)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'input'}: {e['msg']}" for e in exc.errors()
            )
            raise ToolValidationError(f"Invalid input for {name}: {problems}") from exc


def result_block(tool_use_id: str, payload: Any, is_error: bool = False) -> dict[str, Any]:
    """Wrap tool output as untrusted data and strip anything that looks like an injection."""
    if is_error:
        content = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    else:
        content = json.dumps({"untrusted_data": True, "result": payload}, default=str)
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


# --- handlers ---------------------------------------------------------------------------


def _customer(ctx: ToolContext, account_id: str) -> dict[str, Any]:
    customer = ctx.repo.customer(account_id)
    if customer is None:
        raise NotFoundError(f"No account {account_id}.", hint="Ask the caller to re-check it.")
    return customer


def verify_customer(ctx: ToolContext, args: VerifyInput) -> dict[str, Any]:
    if ctx.state.failed_verifications >= MAX_VERIFY_ATTEMPTS:
        raise PolicyViolationError(
            "Verification locked after repeated failures.",
            hint="Escalate to a human (category 'other') for manual identity checks.",
        )
    customer = ctx.repo.customer(args.account_id)
    if customer is None or normalise_postcode(customer["postcode"]) != normalise_postcode(
        args.postcode
    ):
        ctx.state.failed_verifications += 1
        remaining = MAX_VERIFY_ATTEMPTS - ctx.state.failed_verifications
        # Same message whether the account or the postcode is wrong (no account enumeration).
        return {"verified": False, "attempts_remaining": remaining}
    ctx.state.verified_account = args.account_id
    return {
        "verified": True,
        "account_id": args.account_id,
        "first_name": customer["full_name"].split()[0],
    }


def get_account_summary(ctx: ToolContext, args: AccountInput) -> dict[str, Any]:
    policy.require_verified(ctx.state, args.account_id)
    c = _customer(ctx, args.account_id)
    return {
        "account_id": c["account_id"],
        "name": c["full_name"],
        "status": c["status"],
        "plan": c["plan_name"],
        "technology": c["technology"],
        "download_mbps": c["download_mbps"],
        "min_guaranteed_mbps": c["min_guaranteed_mbps"],
        "monthly_price_gbp": c["monthly_price_gbp"],
        "contract_end": c["contract_end"],
        "exchange": c["exchange_name"],
        "region": c["region"],
        "priority_care": bool(c["vulnerable"]),
        "priority_care_note": c["vulnerability_note"],
        "open_tickets": [t for t in ctx.repo.tickets(args.account_id) if t["status"] == "open"],
    }


def check_area_outage(ctx: ToolContext, args: AccountInput) -> dict[str, Any]:
    policy.require_verified(ctx.state, args.account_id)
    c = _customer(ctx, args.account_id)
    outages = ctx.repo.active_outages(c["exchange_id"], ctx.now)
    items = []
    for o in outages:
        comp = policy.outage_compensation(
            datetime.fromisoformat(o["started_at"]), ctx.now, ctx.settings
        )
        items.append(
            {
                "outage_id": o["outage_id"],
                "description": o["description"],
                "started_at": o["started_at"],
                "estimated_restore": o["est_restore_at"],
                "compensation": comp.__dict__,
            }
        )
    return {"exchange": c["exchange_name"], "active_outages": items, "outage_in_area": bool(items)}


def run_line_test(ctx: ToolContext, args: AccountInput) -> dict[str, Any]:
    policy.require_verified(ctx.state, args.account_id)
    c = _customer(ctx, args.account_id)
    line = ctx.repo.line_profile(args.account_id)
    if line is None:
        raise NotFoundError("No line record for this account.")
    if line["fault_code"]:
        result = "fault"
    elif line["sync_down_mbps"] < c["min_guaranteed_mbps"]:
        result = "degraded"
    else:
        result = "ok"
    out = {
        "result": result,
        "fault_code": line["fault_code"],
        "sync_down_mbps": line["sync_down_mbps"],
        "plan_mbps": c["download_mbps"],
        "min_guaranteed_mbps": c["min_guaranteed_mbps"],
        "noise_margin_db": line["noise_margin_db"],
    }
    ctx.state.line_tests[args.account_id] = out
    return out


def get_billing_history(ctx: ToolContext, args: BillingInput) -> dict[str, Any]:
    policy.require_verified(ctx.state, args.account_id)
    invoices = ctx.repo.invoices(args.account_id, args.months)
    keys = Counter((i["period"], i["description"], i["amount_gbp"]) for i in invoices)
    duplicates = []
    seen: set[tuple[str, str, float]] = set()
    for inv in invoices:
        key = (inv["period"], inv["description"], inv["amount_gbp"])
        if keys[key] > 1:
            if key in seen:
                duplicates.append(
                    {
                        "invoice_id": inv["invoice_id"],
                        "period": inv["period"],
                        "description": inv["description"],
                        "amount_gbp": inv["amount_gbp"],
                    }
                )
            seen.add(key)
    return {
        "invoices": [
            {k: inv[k] for k in ("invoice_id", "period", "description", "amount_gbp", "status")}
            for inv in invoices
        ],
        "suspected_duplicates": duplicates,
        "total_billed_gbp": round(sum(i["amount_gbp"] for i in invoices), 2),
    }


def search_help_articles(ctx: ToolContext, args: SearchInput) -> dict[str, Any]:
    terms = [t for t in re.findall(r"[a-z0-9-]+", args.query.lower()) if len(t) > 2]
    results = []
    for art in ctx.repo.search_articles(terms):
        body, findings = neutralise(art["body"])
        if findings:
            ctx.state.injection_suspected = True
            for f in findings:
                ctx.state.record_guardrail("tool_output_injection", f.rule, art["article_id"])
                ctx.tracer.event(
                    ctx.step,
                    "guardrail",
                    "tool_output_injection",
                    "blocked",
                    article=art["article_id"],
                    rule=f.rule,
                )
        results.append({"article_id": art["article_id"], "title": art["title"], "body": body})
        ctx.state.cited_articles.append(art["article_id"])
    return {"articles": results, "count": len(results)}


def apply_bill_credit(ctx: ToolContext, args: CreditInput) -> dict[str, Any]:
    policy.require_verified(ctx.state, args.account_id)
    is_billing_error = args.category == "billing_error"
    if is_billing_error:
        inv = ctx.repo.invoice(args.invoice_id or "")
        if inv is None or inv["account_id"] != args.account_id:
            raise ToolValidationError(
                "billing_error credits need the invoice_id of the duplicated line.",
                hint="Call get_billing_history and use an id from suspected_duplicates.",
            )
        if abs(inv["amount_gbp"] - args.amount_gbp) > 0.005:
            raise PolicyViolationError(
                f"Refund £{args.amount_gbp:.2f} does not match invoice £{inv['amount_gbp']:.2f}.",
                hint="Refund exactly the duplicated amount.",
            )
    key = f"{args.account_id}:{args.category}:{args.invoice_id or args.reason.lower()}"
    existing = ctx.repo.credit_by_key(key)
    if existing:  # idempotent: a retried call never double-credits
        return {
            "applied": True,
            "duplicate_request": True,
            "credit_id": existing["credit_id"],
            "amount_gbp": existing["amount_gbp"],
        }
    prior = [
        c
        for c in ctx.repo.credits_since(args.account_id, ctx.now - timedelta(days=90))
        if not c["reason"].startswith("Billing error")
    ]
    decision = policy.credit_decision(
        ctx.settings, args.amount_gbp, len(prior), ctx.state.injection_suspected, is_billing_error
    )
    if decision.route is policy.CreditRoute.DENY:
        raise PolicyViolationError(decision.reason, hint="Use escalate_to_human.")
    approver = "agent:auto"
    if decision.route is policy.CreditRoute.APPROVAL:
        approved, approver = ctx.approval.approve(
            ApprovalRequest(
                "apply_bill_credit",
                args.account_id,
                f"£{args.amount_gbp:.2f} {args.category} credit: {args.reason}",
                {"decision_reason": decision.reason, **args.model_dump()},
            )
        )
        ctx.tracer.event(
            ctx.step,
            "approval",
            "apply_bill_credit",
            "approved" if approved else "denied",
            reviewer=approver,
        )
        if not approved:
            raise ApprovalDeniedError(
                "A team leader declined this credit.",
                hint="Tell the customer it could not be approved now and offer a hand-off.",
            )
    reason = ("Billing error: " if is_billing_error else "Goodwill: ") + args.reason
    credit = ctx.repo.insert_credit(
        args.account_id, args.amount_gbp, reason, key, approver, ctx.now
    )
    record = {
        "credit_id": credit["credit_id"],
        "amount_gbp": credit["amount_gbp"],
        "category": args.category,
        "approved_by": approver,
    }
    ctx.state.credits_applied.append(record)
    return {"applied": True, **record}


def list_engineer_slots(ctx: ToolContext, args: AccountInput) -> dict[str, Any]:
    policy.require_verified(ctx.state, args.account_id)
    c = _customer(ctx, args.account_id)
    return {"region": c["region"], "slots": ctx.repo.free_slots(c["region"], ctx.now)}


def book_engineer_visit(ctx: ToolContext, args: BookInput) -> dict[str, Any]:
    policy.require_verified(ctx.state, args.account_id)
    c = _customer(ctx, args.account_id)
    policy.check_engineer_allowed(
        ctx.state.line_tests.get(args.account_id),
        ctx.repo.active_outages(c["exchange_id"], ctx.now),
    )
    slot = ctx.repo.slot(args.slot_id)
    if slot is None or slot["region"] != c["region"]:
        raise NotFoundError("Unknown slot for this region.", hint="Call list_engineer_slots.")
    if slot["booked_account"]:
        raise ConflictError("That slot is already taken.", hint="Pick another free slot.")
    approved, approver = ctx.approval.approve(
        ApprovalRequest(
            "book_engineer_visit",
            args.account_id,
            f"Engineer visit {slot['slot_date']} {slot['time_window']} (possible £75 charge if the "
            "fault is in home wiring)",
            {"slot": slot, "line_test": ctx.state.line_tests[args.account_id]},
        )
    )
    ctx.tracer.event(
        ctx.step,
        "approval",
        "book_engineer_visit",
        "approved" if approved else "denied",
        reviewer=approver,
    )
    if not approved:
        raise ApprovalDeniedError(
            "The booking was not approved.",
            hint="Raise a fault ticket via escalate_to_human instead.",
        )
    if not ctx.repo.book_slot(args.slot_id, args.account_id, slot["version"]):
        raise ConflictError(
            "The slot was booked by someone else a moment ago.",
            hint="Call list_engineer_slots and choose again.",
        )
    ticket = ctx.repo.insert_ticket(
        args.account_id,
        "fault",
        policy.triage_priority(c, "fault"),
        f"Engineer visit {slot['slot_date']} {slot['time_window']}",
        ctx.now,
    )
    booking = {
        "slot_id": args.slot_id,
        "date": slot["slot_date"],
        "window": slot["time_window"],
        "ticket_id": ticket,
    }
    ctx.state.bookings.append(booking)
    ctx.state.tickets.append(ticket)
    return {"booked": True, **booking}


def escalate_to_human(ctx: ToolContext, args: EscalateInput) -> dict[str, Any]:
    customer: dict[str, Any] = {}
    if args.account_id:
        policy.require_verified(ctx.state, args.account_id)
        customer = _customer(ctx, args.account_id)
    queue = policy.queue_for(args.category)
    priority = policy.triage_priority(customer, args.category)
    if customer.get("vulnerable"):
        queue = policy.HANDOFF_QUEUES["priority_care"]
    ticket = ctx.repo.insert_ticket(args.account_id, args.category, priority, args.summary, ctx.now)
    ctx.state.handoff = Handoff(
        queue=queue, reason=args.summary, priority=priority, ticket_id=ticket
    )
    ctx.state.tickets.append(ticket)
    callback = "within 1 hour" if priority == "urgent" else "within 1 working day"
    return {
        "handed_off": True,
        "queue": queue,
        "priority": priority,
        "ticket_id": ticket,
        "expected_callback": callback,
    }


def build_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            Tool(
                "verify_customer",
                "Verify the caller's identity with account number and billing "
                "postcode. Must succeed before any account tool.",
                VerifyInput,
                verify_customer,
            ),
            Tool(
                "get_account_summary",
                "Plan, contract, priority-care flag and open tickets.",
                AccountInput,
                get_account_summary,
            ),
            Tool(
                "check_area_outage",
                "Active outages at the customer's exchange, with automatic compensation due.",
                AccountInput,
                check_area_outage,
            ),
            Tool(
                "run_line_test",
                "Remote line test: ok, degraded (below guaranteed speed) or fault.",
                AccountInput,
                run_line_test,
            ),
            Tool(
                "get_billing_history",
                "Invoices for the last N months and suspected duplicate charges.",
                BillingInput,
                get_billing_history,
            ),
            Tool(
                "search_help_articles",
                "Search the help centre. Cite article ids in replies.",
                SearchInput,
                search_help_articles,
            ),
            Tool(
                "apply_bill_credit",
                "Apply a bill credit. billing_error refunds a duplicated "
                "invoice line (needs invoice_id); goodwill is discretionary. Limits and human "
                "approval are enforced.",
                CreditInput,
                apply_bill_credit,
                side_effect=True,
            ),
            Tool(
                "list_engineer_slots",
                "Free engineer appointments in the customer's region.",
                AccountInput,
                list_engineer_slots,
            ),
            Tool(
                "book_engineer_visit",
                "Book an engineer. Only after a line test shows a fault and "
                "with no area outage; a human approves.",
                BookInput,
                book_engineer_visit,
                side_effect=True,
            ),
            Tool(
                "escalate_to_human",
                "Hand the conversation to a human team with a summary. Use for "
                "cancellations, complaints, anything over your limits, or priority-care faults.",
                EscalateInput,
                escalate_to_human,
                side_effect=True,
            ),
        ]
    )
