"""The MCP server through the real protocol (in-memory transport)."""

import pytest

pytestmark = pytest.mark.anyio


async def test_lists_tools_with_annotations(gateway):
    tools = {t.name: t for t in await gateway.list_tools()}
    assert len(tools) == 9
    assert tools["calculate_deadline"].read_only
    assert not tools["draft_decision_notice"].read_only
    assert "approved_by" in tools["draft_decision_notice"].input_schema["properties"]


async def test_resources_and_prompt(gateway):
    resources = await gateway.session.list_resources()
    assert any(str(r.uri) == "planning://policies" for r in resources.resources)
    read = await gateway.session.read_resource("planning://applications/26/00417/HOU")
    assert "Mill Lane" in read.contents[0].text
    prompt = await gateway.session.get_prompt("officer_report", {"ref": "26/00417/HOU"})
    assert "26/00417/HOU" in prompt.messages[0].content.text


async def test_overdue_search_paginates(gateway):
    first = (await gateway.call("search_applications", {"overdue_only": True, "limit": 5})).json()
    assert len(first["results"]) == 5 and all(r["overdue"] for r in first["results"])
    second = (
        await gateway.call(
            "search_applications",
            {"overdue_only": True, "limit": 5, "cursor": first["next_cursor"]},
        )
    ).json()
    refs = [r["ref"] for r in first["results"] + second["results"]]
    assert len(refs) == len(set(refs)) and refs == sorted(refs)


async def test_comment_text_only_on_request_and_marked_untrusted(gateway):
    plain = (await gateway.call("summarise_consultations", {"ref": "26/00417/HOU"})).json()
    assert "untrusted_public_comment_text" not in plain
    full = (
        await gateway.call(
            "summarise_consultations", {"ref": "26/00417/HOU", "include_comment_text": True}
        )
    ).json()
    assert any("SYSTEM:" in c["text"] for c in full["untrusted_public_comment_text"])


async def test_writes_need_approver_and_are_audited(gateway, store):
    args = {"ref": "26/00733/ADV", "recommendation": "approve", "reasons": [],
            "conditions": [], "idempotency_key": "test-key-1"}  # fmt: skip
    refused = await gateway.call("draft_decision_notice", args)
    assert refused.is_error and "human approver" in refused.text
    ok = await gateway.call("draft_decision_notice", {**args, "approved_by": "C. Mistry"})
    assert not ok.is_error and ok.json()["created"]
    outcomes = [a["outcome"] for a in store.audit_log()]
    assert outcomes[0] == "refused: no human approval" and outcomes[1].startswith("draft 1")


async def test_extension_of_time_round_trip(gateway):
    out = await gateway.call(
        "record_extension_of_time",
        {"ref": "26/00417/HOU", "new_date": "2027-01-29",
         "reason": "Applicant agreed in writing on 20 November.", "approved_by": "C. Mistry"},
    )  # fmt: skip
    assert not out.is_error, out.text
    d = (await gateway.call("calculate_deadline", {"ref": "26/00417/HOU"})).json()
    assert d["effective_date"] == "2027-01-29" and not d["overdue"]


@pytest.mark.parametrize(
    ("tool", "args", "fragment"),
    [
        ("get_application", {"ref": "26/99999/HOU"}, "no application"),
        ("get_policy", {"policy_id": "ZZ9"}, "known policies"),
        ("recommend_route", {"ref": "26/00417/HOU", "recommendation": "maybe"}, "approve"),
        ("search_applications", {"status": "lost"}, "unknown status"),
        ("record_extension_of_time",
         {"ref": "26/00417/HOU", "new_date": "2028-01-01", "reason": "long enough reason",
          "approved_by": "x y"}, "six months"),
    ],
)  # fmt: skip
async def test_tool_errors_are_helpful(gateway, tool, args, fragment):
    out = await gateway.call(tool, args)
    assert out.is_error and fragment in out.text
