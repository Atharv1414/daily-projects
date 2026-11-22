from __future__ import annotations

from datetime import timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from broadband_support_agent import policy
from broadband_support_agent.config import Settings
from broadband_support_agent.errors import PolicyViolationError, VerificationRequiredError
from broadband_support_agent.policy import CreditRoute
from broadband_support_agent.state import SessionState

S = Settings()


@pytest.mark.parametrize(
    ("amount", "prior", "injected", "billing", "route"),
    [
        (5.0, 0, False, False, CreditRoute.AUTO),
        (15.0, 0, False, False, CreditRoute.AUTO),
        (15.01, 0, False, False, CreditRoute.APPROVAL),
        (60.0, 0, False, False, CreditRoute.APPROVAL),
        (60.01, 0, False, False, CreditRoute.DENY),
        (5.0, 2, False, False, CreditRoute.DENY),
        (5.0, 2, False, True, CreditRoute.AUTO),  # billing errors bypass the goodwill cap
        (5.0, 0, True, False, CreditRoute.APPROVAL),  # injection forces human review
        (0.0, 0, False, False, CreditRoute.DENY),
        (float("nan"), 0, False, False, CreditRoute.DENY),
    ],
)
def test_credit_routing(amount, prior, injected, billing, route):
    assert policy.credit_decision(S, amount, prior, injected, billing).route is route


@given(st.floats(min_value=0.01, max_value=10_000), st.integers(0, 5), st.booleans())
def test_credit_never_auto_above_auto_limit(amount, prior, billing):
    decision = policy.credit_decision(S, amount, prior, False, billing)
    if amount > S.credit_auto_limit:
        assert decision.route is not CreditRoute.AUTO
    if amount > S.credit_approval_limit:
        assert decision.route is CreditRoute.DENY


@given(st.integers(min_value=0, max_value=60 * 24 * 30))
def test_compensation_is_monotonic_and_bounded(minutes):
    start = S.now - timedelta(minutes=minutes)
    comp = policy.outage_compensation(start, S.now, S)
    later = policy.outage_compensation(start - timedelta(days=1), S.now, S)
    assert later.amount_gbp >= comp.amount_gbp
    assert comp.days <= max(0, minutes // (60 * 24) - S.compensation_grace_days)


def test_compensation_examples():
    assert not policy.outage_compensation(S.now - timedelta(days=1), S.now, S).eligible
    three = policy.outage_compensation(S.now - timedelta(days=3, hours=1), S.now, S)
    assert three.eligible and three.days == 1 and three.amount_gbp == pytest.approx(9.76)
    assert not policy.outage_compensation(S.now + timedelta(hours=1), S.now, S).eligible


def test_require_verified():
    state = SessionState("s")
    with pytest.raises(VerificationRequiredError):
        policy.require_verified(state, "NW-100001")
    state.verified_account = "NW-100001"
    policy.require_verified(state, "NW-100001")
    with pytest.raises(VerificationRequiredError):
        policy.require_verified(state, "NW-100002")


def test_engineer_rules():
    with pytest.raises(PolicyViolationError, match="outage"):
        policy.check_engineer_allowed({"result": "fault"}, [{"outage_id": "X"}])
    with pytest.raises(PolicyViolationError, match="No line test"):
        policy.check_engineer_allowed(None, [])
    with pytest.raises(PolicyViolationError, match="passed"):
        policy.check_engineer_allowed({"result": "ok"}, [])
    policy.check_engineer_allowed({"result": "fault"}, [])


def test_triage_and_queues():
    assert policy.triage_priority({"vulnerable": 1}, "billing") == "urgent"
    assert policy.triage_priority({}, "fault") == "high"
    assert policy.queue_for("retention") == "Retentions team"
    with pytest.raises(PolicyViolationError):
        policy.queue_for("shouting")
