from __future__ import annotations

import pytest

from broadband_support_agent.errors import (
    ApprovalDeniedError,
    ConflictError,
    PolicyViolationError,
    ToolValidationError,
    UnknownToolError,
    VerificationRequiredError,
)
from broadband_support_agent.tools import (
    AccountInput,
    BookInput,
    CreditInput,
    VerifyInput,
    build_registry,
    normalise_postcode,
)

REG = build_registry()


def run(ctx, name, **kw):
    tool, args = REG.validate(name, kw)
    return tool.handler(ctx, args)


def test_registry_specs_are_valid_tool_definitions():
    specs = REG.specs()
    assert len(specs) == 10
    for spec in specs:
        assert spec["input_schema"]["type"] == "object"
        assert spec["description"]


def test_unknown_tool_and_extra_fields_rejected():
    with pytest.raises(UnknownToolError):
        REG.validate("drop_tables", {})
    with pytest.raises(ToolValidationError):
        REG.validate("run_line_test", {"account_id": "NW-100002", "sudo": True})
    with pytest.raises(ToolValidationError):
        REG.validate("verify_customer", {"account_id": "NW-100002", "postcode": "12345"})


@pytest.mark.parametrize("raw", ["ls6 2ab", "LS62AB", " LS6  2AB "])
def test_postcode_normalisation(raw):
    assert normalise_postcode(raw) == "LS62AB"


def test_verification_flow_and_lockout(make_ctx):
    ctx = make_ctx()
    assert run(ctx, "verify_customer", account_id="NW-100001", postcode="ls62ab")["verified"]
    ctx = make_ctx()
    for _ in range(3):
        out = run(ctx, "verify_customer", account_id="NW-100001", postcode="LS1 1AA")
        assert not out["verified"]
    with pytest.raises(PolicyViolationError, match="locked"):
        run(ctx, "verify_customer", account_id="NW-100001", postcode="LS6 2AB")


def test_unknown_account_looks_like_wrong_postcode(make_ctx):
    out = run(make_ctx(), "verify_customer", account_id="NW-999999", postcode="LS6 2AB")
    assert out == {"verified": False, "attempts_remaining": 2}


def test_account_tools_require_verification(make_ctx):
    with pytest.raises(VerificationRequiredError):
        run(make_ctx(), "get_account_summary", account_id="NW-100001")


def test_outage_and_compensation(make_ctx):
    out = run(make_ctx("NW-100001"), "check_area_outage", account_id="NW-100001")
    assert out["outage_in_area"]
    assert out["active_outages"][0]["compensation"]["amount_gbp"] == pytest.approx(9.76)
    assert not run(make_ctx("NW-100002"), "check_area_outage", account_id="NW-100002")[
        "outage_in_area"
    ]


@pytest.mark.parametrize(
    ("account", "result"), [("NW-100002", "fault"), ("NW-100007", "ok"), ("NW-100005", "fault")]
)
def test_line_test_results(make_ctx, account, result):
    assert run(make_ctx(account), "run_line_test", account_id=account)["result"] == result


def test_billing_duplicates_detected(make_ctx):
    out = run(make_ctx("NW-100004"), "get_billing_history", account_id="NW-100004", months=1)
    dups = out["suspected_duplicates"]
    assert [d["amount_gbp"] for d in dups] == [7.99]


def test_billing_error_credit_is_idempotent(make_ctx, repo):
    ctx = make_ctx("NW-100004")
    kw = dict(
        account_id="NW-100004",
        amount_gbp=7.99,
        category="billing_error",
        reason="Duplicate router fee",
        invoice_id="INV-100004-202611-R2",
    )
    first = run(ctx, "apply_bill_credit", **kw)
    second = run(ctx, "apply_bill_credit", **kw)
    assert first["applied"] and second["duplicate_request"]
    assert len(repo.credits_since("NW-100004", ctx.now.replace(year=2020))) == 1


def test_billing_error_needs_matching_invoice(make_ctx):
    ctx = make_ctx("NW-100004")
    with pytest.raises(ToolValidationError):
        run(
            ctx,
            "apply_bill_credit",
            account_id="NW-100004",
            amount_gbp=7.99,
            category="billing_error",
            reason="Duplicate fee",
        )
    with pytest.raises(PolicyViolationError, match="does not match"):
        run(
            ctx,
            "apply_bill_credit",
            account_id="NW-100004",
            amount_gbp=9.99,
            category="billing_error",
            reason="Duplicate fee",
            invoice_id="INV-100004-202611-R2",
        )


def test_credit_approval_denied_writes_nothing(make_ctx, repo):
    ctx = make_ctx("NW-100007", approvals=[False])
    with pytest.raises(ApprovalDeniedError):
        run(
            ctx,
            "apply_bill_credit",
            account_id="NW-100007",
            amount_gbp=30.0,
            category="goodwill",
            reason="Slow speeds for a week",
        )
    assert ctx.state.credits_applied == []
    assert repo.credits_since("NW-100007", ctx.now.replace(year=2020)) == []


def test_booking_requires_fault_and_handles_conflicts(make_ctx, repo):
    ctx = make_ctx("NW-100002", approvals=[True, True])
    with pytest.raises(PolicyViolationError):  # no line test yet
        run(ctx, "book_engineer_visit", account_id="NW-100002", slot_id="SL-NOR-1123-AM")
    run(ctx, "run_line_test", account_id="NW-100002")
    slot = run(ctx, "list_engineer_slots", account_id="NW-100002")["slots"][0]
    booked = run(ctx, "book_engineer_visit", account_id="NW-100002", slot_id=slot["slot_id"])
    assert booked["booked"] and ctx.state.bookings
    with pytest.raises(ConflictError):
        run(ctx, "book_engineer_visit", account_id="NW-100002", slot_id=slot["slot_id"])


def test_optimistic_lock_rejects_stale_version(repo):
    slot = repo.free_slots("North", repo_now())[0]
    assert repo.book_slot(slot["slot_id"], "NW-100002", slot["version"])
    assert not repo.book_slot(slot["slot_id"], "NW-100007", slot["version"])


def repo_now():
    from broadband_support_agent.config import Settings

    return Settings().now


def test_vulnerable_handoff_goes_to_priority_care(make_ctx):
    out = run(
        make_ctx("NW-100005"),
        "escalate_to_human",
        account_id="NW-100005",
        category="fault",
        summary="Line dropping, medical equipment at home",
    )
    assert out["queue"] == "Priority care team" and out["priority"] == "urgent"
    assert out["expected_callback"] == "within 1 hour"


def test_help_search_neutralises_injected_article(make_ctx):
    ctx = make_ctx()
    out = run(ctx, "search_help_articles", query="router settings faster")
    bodies = " ".join(a["body"] for a in out["articles"])
    assert "SYSTEM OVERRIDE" not in bodies and ctx.state.injection_suspected


def test_input_models_reject_bad_values():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AccountInput(account_id="100001")
    with pytest.raises(ValidationError):
        CreditInput(account_id="NW-100001", amount_gbp=-5, category="goodwill", reason="xxxxx")
    with pytest.raises(ValidationError):
        BookInput(account_id="NW-100001", slot_id="tomorrow")
    assert VerifyInput(account_id="NW-100001", postcode="LS6 2AB").postcode == "LS6 2AB"
