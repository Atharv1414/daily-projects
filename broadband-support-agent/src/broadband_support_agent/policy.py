"""Business rules, as plain deterministic functions.

Keeping policy out of the prompt means it is enforced even if the model is wrong, confused or
manipulated, and it can be unit-tested exhaustively (including property-based tests).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from broadband_support_agent.config import Settings
from broadband_support_agent.errors import PolicyViolationError, VerificationRequiredError
from broadband_support_agent.state import SessionState


class CreditRoute(StrEnum):
    AUTO = "auto"
    APPROVAL = "approval"
    DENY = "deny"


@dataclass(frozen=True)
class CreditDecision:
    route: CreditRoute
    reason: str


def require_verified(state: SessionState, account_id: str) -> None:
    if state.verified_account is None:
        raise VerificationRequiredError(
            "The caller has not passed identity verification.",
            hint="Call verify_customer with the account number and postcode first.",
        )
    if state.verified_account != account_id:
        raise VerificationRequiredError(
            f"This session is verified for {state.verified_account}, not {account_id}.",
            hint="Only act on the verified account.",
        )


def credit_decision(
    settings: Settings,
    amount: float,
    prior_credits_90d: int,
    injection_suspected: bool,
    is_billing_error: bool,
) -> CreditDecision:
    """Route a requested bill credit.

    * Refunds of a proven billing error (duplicate charge) are not goodwill and do not count
      towards the 90-day goodwill cap, but still respect the monetary limits.
    * If a prompt injection was seen in this session, every credit needs a human.
    """
    if not math.isfinite(amount) or amount <= 0:
        return CreditDecision(CreditRoute.DENY, "Credit amount must be a positive number.")
    if amount > settings.credit_approval_limit:
        return CreditDecision(
            CreditRoute.DENY,
            f"£{amount:.2f} exceeds the £{settings.credit_approval_limit:.2f} limit for "
            "agent-issued credits; hand off to the billing team.",
        )
    if not is_billing_error and prior_credits_90d >= settings.max_credits_per_90_days:
        return CreditDecision(
            CreditRoute.DENY,
            f"Account already has {prior_credits_90d} goodwill credits in 90 days "
            f"(cap {settings.max_credits_per_90_days}); hand off to a team leader.",
        )
    if injection_suspected:
        return CreditDecision(
            CreditRoute.APPROVAL, "Possible prompt injection in this session; human review."
        )
    if amount <= settings.credit_auto_limit:
        return CreditDecision(CreditRoute.AUTO, "Within the automatic credit limit.")
    return CreditDecision(CreditRoute.APPROVAL, "Above the automatic limit; needs approval.")


def check_engineer_allowed(
    line_test: dict[str, Any] | None, active_outages: list[dict[str, Any]]
) -> None:
    if active_outages:
        raise PolicyViolationError(
            "There is an active outage at the customer's exchange; a home visit will not help.",
            hint="Explain the outage and its estimated restore time instead.",
        )
    if line_test is None:
        raise PolicyViolationError(
            "No line test has been run in this session.",
            hint="Run run_line_test first; visits are only booked for confirmed faults.",
        )
    if line_test.get("result") != "fault":
        raise PolicyViolationError(
            "The line test passed, so an engineer visit cannot be booked.",
            hint="Offer Wi-Fi troubleshooting from the help articles instead.",
        )


@dataclass(frozen=True)
class Compensation:
    eligible: bool
    days: int
    amount_gbp: float
    explanation: str


def outage_compensation(started_at: datetime, now: datetime, settings: Settings) -> Compensation:
    """Automatic compensation for a loss of service.

    Simplification: counts calendar days (the real scheme counts working days for the grace
    period). Each full day beyond the grace period earns the configured daily rate.
    """
    if started_at > now:
        return Compensation(False, 0, 0.0, "Outage has not started yet.")
    full_days = int((now - started_at).total_seconds() // 86_400)
    payable = max(0, full_days - settings.compensation_grace_days)
    amount = round(payable * settings.compensation_per_day, 2)
    if payable == 0:
        return Compensation(
            False,
            0,
            0.0,
            f"Service loss of {full_days} full day(s) is within the "
            f"{settings.compensation_grace_days}-day grace period.",
        )
    return Compensation(
        True,
        payable,
        amount,
        f"{payable} day(s) beyond the {settings.compensation_grace_days}-day grace period at "
        f"£{settings.compensation_per_day:.2f}/day, applied automatically to the next bill.",
    )


def triage_priority(customer: dict[str, Any], category: str) -> str:
    if customer.get("vulnerable"):
        return "urgent"
    if category in {"fault", "outage"}:
        return "high"
    if category in {"billing", "retention"}:
        return "normal"
    return "low"


HANDOFF_QUEUES = {
    "retention": "Retentions team",
    "billing": "Billing specialists",
    "fault": "Network fault desk",
    "priority_care": "Priority care team",
    "complaint": "Complaints (team leader)",
    "other": "General support",
}


def queue_for(reason_category: str) -> str:
    if reason_category not in HANDOFF_QUEUES:
        raise PolicyViolationError(
            f"Unknown hand-off category {reason_category!r}.",
            hint=f"Use one of: {', '.join(HANDOFF_QUEUES)}.",
        )
    return HANDOFF_QUEUES[reason_category]
