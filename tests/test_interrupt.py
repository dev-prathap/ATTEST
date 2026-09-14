import pytest

pytest.importorskip("langgraph")
from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.graph import END, START, MessagesState, StateGraph  # noqa: E402
from langgraph.prebuilt import ToolNode  # noqa: E402
from langgraph.types import Command  # noqa: E402

from attest import Attest, PendingStore, SqliteLedger  # noqa: E402
from attest.adapters import langgraph as lg  # noqa: E402
from attest.gate.interrupt import InterruptGate  # noqa: E402

MAPPING = {"send_email": {"system": "gmail", "verb": "send", "target": "to"}}


@tool
def send_email(to: str, subject: str) -> dict:
    """Send an email."""
    return {"id": "m1", "subject": subject}


def build(at):
    tools = lg.wrap_tools([send_email], at, mapping=MAPPING)
    g = StateGraph(MessagesState)
    g.add_node("agent", lambda s: {"messages": [AIMessage(content="", tool_calls=[
        {"name": "send_email", "args": {"to": "arun@newco.com", "subject": "Hi"}, "id": "c1"}])]})
    g.add_node("tools", ToolNode(tools))
    g.add_edge(START, "agent")
    g.add_edge("agent", "tools")
    g.add_edge("tools", END)
    return g.compile(checkpointer=MemorySaver())


def test_interrupt_pauses_then_resumes_with_approval():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=InterruptGate(), actor="ram@acme.com")
    app = build(at)
    cfg = {"configurable": {"thread_id": "t1"}}
    out = app.invoke({"messages": []}, cfg)
    assert "__interrupt__" in out
    payload = out["__interrupt__"][0].value
    assert payload["action"] == "gmail.send:arun@newco.com" and payload["target_class"] == "external"
    assert payload["params_preview"] == {"to": "arun@newco.com", "subject": "Hi"} and at.ledger.count() == 0
    out = app.invoke(Command(resume={"status": "edited", "approver": "ram", "edits": {"subject": "Edited"}}), cfg)
    msg = [m for m in out["messages"] if isinstance(m, ToolMessage)][0]
    assert "Edited" in msg.content
    e = at.ledger.last()
    assert e.confirm.status == "edited" and e.confirm.approver == "ram" and e.confirm.channel == "interrupt"
    assert e.verification.level == "acknowledged"


def test_interrupt_rejected_becomes_error_tool_message():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=InterruptGate(), actor="ram@acme.com")
    app = build(at)
    cfg = {"configurable": {"thread_id": "t2"}}
    app.invoke({"messages": []}, cfg)
    out = app.invoke(Command(resume="reject"), cfg)
    msg = [m for m in out["messages"] if isinstance(m, ToolMessage)][0]
    assert "rejected" in msg.content and at.ledger.last().confirm.status == "rejected"


def test_interrupt_with_store_mirrors_request():
    store = PendingStore(":memory:")
    seen = []

    class N:
        name = "n"

        def notify(self, request, store):
            seen.append(request.id)

    at = Attest(ledger=SqliteLedger(":memory:"), gate=InterruptGate(store=store, notifiers=[N()]), actor="ram@acme.com")
    app = build(at)
    cfg = {"configurable": {"thread_id": "t3"}}
    out = app.invoke({"messages": []}, cfg)
    rid = out["__interrupt__"][0].value["id"]
    assert seen == [rid] and store.get(rid)["status"] == "pending"
    app.invoke(Command(resume=True), cfg)
    assert store.decision(rid).status == "approved" and at.ledger.last().confirm.status == "approved"
