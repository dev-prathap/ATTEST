"""Claude Agent SDK hooks, CrewAI wrap, DeerFlow alias — driven with duck-typed inputs."""
import asyncio

import pytest

from attest import ActionRejected, Attest, AutoGate, PendingStore, SqliteLedger, StoreGate
from attest.adapters import claude_agent_sdk as cl
from attest.adapters import crewai as crew
from attest.adapters import deerflow
from attest.adapters.langgraph import AttestMiddleware
from attest.policy import PolicyEngine

MAPPING = {"mcp__gmail__send_message": {"system": "gmail", "verb": "send", "target": "to"},
           "update_deal": {"system": "hubspot", "verb": "update", "target": "deal_id"}}


def run(coro):
    return asyncio.run(coro)


# ── Claude Agent SDK hooks ────────────────────────────────────────────────────
def test_hooks_allow_edit_and_record():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate("approved", approver="ram", edits={"subject": "E"}), actor="ram@acme.com")
    pre, post = cl.hooks(at, mapping=MAPPING)
    out = run(pre({"tool_name": "mcp__gmail__send_message", "tool_input": {"to": "arun@newco.com", "subject": "orig"},
                   "session_id": "s1"}, "tu1", None))
    h = out["hookSpecificOutput"]
    assert h["permissionDecision"] == "allow" and h["updatedInput"]["subject"] == "E"
    assert at.ledger.count() == 0  # nothing recorded until the tool ran
    run(post({"tool_name": "mcp__gmail__send_message", "tool_input": {"to": "arun@newco.com", "subject": "E"},
              "tool_response": {"content": [{"type": "text", "text": '{"id": "m1"}'}]}}, "tu1", None))
    e = at.ledger.last()
    assert e.descriptor["system"] == "gmail" and e.confirm.status == "edited" and e.confirm.approver == "ram"
    assert e.verification.level == "acknowledged" and e.run_id == "s1" and e.descriptor["extra"]["framework"] == "claude-agent-sdk"


def test_hooks_deny_on_refuse_and_reject():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate("rejected", approver="bob"),
                policy=PolicyEngine.from_yaml("policies:\n  - match: {verb: delete}\n    decision: refuse\n"))
    pre, post = cl.hooks(at, mapping=MAPPING)
    out = run(pre({"tool_name": "update_deal", "tool_input": {"deal_id": "1", "dealname": "x"}}, "t1"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"  # medium risk ⇒ act
    out = run(pre({"tool_name": "mcp__gmail__send_message", "tool_input": {"to": "x@ext.com"}}, "t2"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny" and "rejected" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert at.ledger.last().confirm.status == "rejected"
    out = run(pre({"tool_name": "mcp__tracker__delete_issue", "tool_input": {"issue_id": "1"}}, "t3"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny" and "refused" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert at.ledger.last().decision == "refuse" and at.ledger.last().descriptor["system"] == "tracker"


def test_hooks_pending_and_tool_error():
    store = PendingStore(":memory:")
    at = Attest(ledger=SqliteLedger(":memory:"), gate=StoreGate(store, wait=False))
    pre, post = cl.hooks(at, mapping=MAPPING)
    out = run(pre({"tool_name": "mcp__gmail__send_message", "tool_input": {"to": "x@ext.com"}}, "t1"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny" and "resume_token" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert len(store.pending()) == 1 and at.ledger.last().confirm.status == "pending"
    run(pre({"tool_name": "update_deal", "tool_input": {"deal_id": "1"}}, "t2"))
    run(post({"tool_name": "update_deal", "tool_input": {"deal_id": "1"}, "tool_response": {"is_error": True, "content": [{"type": "text", "text": "boom"}]}}, "t2"))
    e = at.ledger.last()
    assert e.execution.status == "failed" and e.verification.level == "attested-only"


def test_post_without_pre_still_records():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate())
    _, post = cl.hooks(at, mapping=MAPPING)
    run(post({"tool_name": "update_deal", "tool_input": {"deal_id": "9"}, "tool_response": {"id": "9"}}, "zz"))
    assert at.ledger.count() == 1 and at.ledger.last().verification.level == "acknowledged"


# ── CrewAI ────────────────────────────────────────────────────────────────────
class FakeCrewTool:
    name = "update_deal"
    description = "update a deal"

    def __init__(self):
        self.calls = []

    def _run(self, deal_id: str, dealname: str = "") -> dict:
        self.calls.append((deal_id, dealname))
        return {"id": deal_id, "dealname": dealname}


def test_crewai_wrap_records_and_edits():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate("approved", edits={"dealname": "EDITED"}))
    at.policy = PolicyEngine.from_yaml("policies:\n  - match: {verb: update}\n    decision: ask\n")
    t = FakeCrewTool()
    [w] = crew.wrap_tools([t], at, mapping=MAPPING)
    assert w.name == "update_deal" and type(w).__name__ == "AttestedFakeCrewTool" and w._attest_wrapped
    assert w._run("7", dealname="orig") == {"id": "7", "dealname": "EDITED"}
    e = at.ledger.last()
    assert e.descriptor["target"] == "7" and e.confirm.status == "edited" and e.descriptor["extra"]["framework"] == "crewai"
    assert w._run("8", "pos") == {"id": "8", "dealname": "EDITED"}  # positional args mapped by name


def test_crewai_rejection_returns_text_or_raises():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate("rejected"))
    at.policy = PolicyEngine.from_yaml("policies:\n  - match: {verb: update}\n    decision: ask\n")
    w = crew.wrap_tool(FakeCrewTool(), at, mapping=MAPPING)
    assert "rejected" in w._run("7")
    w2 = crew.wrap_tool(FakeCrewTool(), at, mapping=MAPPING, raise_on_block=True)
    with pytest.raises(ActionRejected):
        w2._run("7")
    assert run(crew.wrap_tool(FakeCrewTool(), Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate()), mapping=MAPPING)._arun("1")) == {"id": "1", "dealname": ""}


def test_deerflow_is_the_langchain_middleware():
    assert deerflow.AttestMiddleware is AttestMiddleware and callable(deerflow.wrap_tools)
