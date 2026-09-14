import json

import pytest

from attest import ActionPending, Attest, AutoGate, PendingStore, SqliteLedger, StoreGate
from attest.adapters import openai_agents as oa
from attest.gate import ConfirmDecision

MAPPING = {"send_email": {"system": "gmail", "verb": "send", "target": "to"}}


class FakeFunctionTool:
    """Duck-typed stand-in for agents.FunctionTool."""

    def __init__(self, name, fn):
        self.name, self.description, self._fn = name, "doc", fn
        self.params_json_schema = {"type": "object"}

        async def on_invoke_tool(ctx, input_json):
            return self._fn(**json.loads(input_json or "{}"))

        self.on_invoke_tool = on_invoke_tool


async def test_wrap_duck_typed_tool_records_and_edits():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate("approved", edits={"subject": "E"}), actor="ram@acme.com")
    seen = {}
    t = FakeFunctionTool("send_email", lambda to, subject: seen.update(subject=subject) or {"id": "m1"})
    w = oa.wrap_tool(t, at, mapping=MAPPING)
    out = await w.on_invoke_tool(None, json.dumps({"to": "arun@newco.com", "subject": "orig"}))
    assert out == {"id": "m1"} and seen["subject"] == "E"
    e = at.ledger.last()
    assert e.descriptor["system"] == "gmail" and e.descriptor["target"] == "arun@newco.com"
    assert e.confirm.status == "edited" and e.descriptor["extra"]["framework"] == "openai-agents"
    assert w.name == "send_email" and w.description == "doc"


async def test_rejection_returns_text_and_pending_returns_token():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate("rejected", approver="bob"))
    w = oa.wrap_tool(FakeFunctionTool("send_email", lambda to: 1), at, mapping=MAPPING)
    assert "rejected" in await w.on_invoke_tool(None, '{"to": "x@ext.com"}')

    store = PendingStore(":memory:")
    at2 = Attest(ledger=SqliteLedger(":memory:"), gate=StoreGate(store, wait=False))
    w2 = oa.wrap_tool(FakeFunctionTool("send_email", lambda to: {"id": 9}), at2, mapping=MAPPING)
    out = json.loads(await w2.on_invoke_tool(None, '{"to": "x@ext.com"}'))
    assert out["status"] == "pending_confirmation"
    store.decide(out["resume_token"], ConfirmDecision("approved", "ram"))
    assert await oa.resume(at2, out["resume_token"]) == {"id": 9}
    w3 = oa.wrap_tool(FakeFunctionTool("send_email", lambda to: 1), at2, mapping=MAPPING, raise_on_block=True)
    with pytest.raises(ActionPending):
        await w3.on_invoke_tool(None, '{"to": "y@ext.com"}')


async def test_non_json_input_is_wrapped():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate())
    w = oa.wrap_tool(FakeFunctionTool("lookup", lambda input: {"id": input}), at, mapping={"lookup": {"system": "x", "verb": "get"}})
    assert await w.on_invoke_tool(None, "plain text") == {"id": "plain text"}


async def test_real_function_tool():
    agents = pytest.importorskip("agents")
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), actor="ram@acme.com")

    @agents.function_tool
    def update_deal(deal_id: str, dealname: str) -> dict:
        """Update a deal."""
        return {"id": deal_id, "dealname": dealname}

    [w] = oa.wrap_tools([update_deal], at, mapping={"update_deal": {"system": "hubspot", "verb": "update", "target": "deal_id"}})
    assert isinstance(w, agents.FunctionTool) and w.name == "update_deal"
    from agents.tool_context import ToolContext
    args = '{"deal_id": "7", "dealname": "Acme"}'
    ctx = ToolContext(context=None, tool_name="update_deal", tool_call_id="c1", tool_arguments=args,
                      run_config=agents.RunConfig())
    out = await w.on_invoke_tool(ctx, args)
    assert json.loads(out)["id"] == "7" if isinstance(out, str) else out["id"] == "7"
    e = at.ledger.last()
    assert e.descriptor["system"] == "hubspot" and e.descriptor["target"] == "7" and e.verification.level == "acknowledged"
