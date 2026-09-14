import pytest

pytest.importorskip("langgraph")
from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langgraph.graph import END, START, MessagesState, StateGraph  # noqa: E402
from langgraph.prebuilt import ToolNode  # noqa: E402

from attest import ActionRejected, Attest, AutoGate, SqliteLedger  # noqa: E402
from attest.adapters import langgraph as lg  # noqa: E402

MAPPING = {
    "send_email": {"system": "gmail", "verb": "send", "target": "to"},
    "update_deal": {"system": "hubspot", "verb": "update", "target": "deal_id"},
}


@tool
def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email."""
    return {"id": "m1", "threadId": "t1"}


@tool
def update_deal(deal_id: str, dealname: str) -> dict:
    """Update a HubSpot deal."""
    return {"id": deal_id, "ok": True}


@tool
async def async_ping(x: int) -> dict:
    """Async tool."""
    return {"id": x}


def scripted_graph(tools, calls):
    """A graph with no LLM: the agent node emits fixed tool calls, the ToolNode executes them."""
    g = StateGraph(MessagesState)
    g.add_node("agent", lambda s: {"messages": [AIMessage(content="", tool_calls=calls)]})
    g.add_node("tools", ToolNode(tools))
    g.add_edge(START, "agent")
    g.add_edge("agent", "tools")
    g.add_edge("tools", END)
    return g


CALLS = [
    {"name": "send_email", "args": {"to": "arun@newco.com", "subject": "Hi", "body": "…"}, "id": "c1"},
    {"name": "update_deal", "args": {"deal_id": "777", "dealname": "Acme"}, "id": "c2"},
]


@pytest.fixture
def at():
    return Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(approver="tester"), agent="lg-agent", actor="ram@acme.com")


def test_wrap_tools_records_every_call(at):
    tools = lg.wrap_tools([send_email, update_deal], at, mapping=MAPPING)
    assert all(t.name in MAPPING for t in tools) and tools[0].description == "Send an email."
    out = scripted_graph(tools, CALLS).compile().invoke({"messages": []})
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 2 and "m1" in tool_msgs[0].content
    entries = at.ledger.entries()
    assert [(e.descriptor["system"], e.descriptor["verb"], e.descriptor["target"]) for e in entries] == [
        ("gmail", "send", "arun@newco.com"), ("hubspot", "update", "777")]
    assert entries[0].decision == "ask" and entries[0].confirm.status == "approved"
    assert entries[1].decision == "act" and entries[1].verification.level == "acknowledged"
    assert entries[0].agent == "lg-agent" and entries[0].descriptor["extra"]["framework"] == "langgraph"


def test_wrap_graph_patches_tool_node_in_place(at):
    g = scripted_graph([send_email, update_deal], CALLS).compile()
    assert lg.wrap(g, at, mapping=MAPPING) is g
    g.invoke({"messages": []})
    assert at.ledger.count() == 2
    lg.wrap(g, at, mapping=MAPPING)  # idempotent: already-wrapped tools are skipped
    g.invoke({"messages": []})
    assert at.ledger.count() == 4


def test_wrap_uncompiled_graph(at):
    g = scripted_graph([send_email], CALLS[:1])
    lg.wrap(g, at, mapping=MAPPING)
    g.compile().invoke({"messages": []})
    assert at.ledger.count() == 1


def test_wrap_without_tool_node_raises(at):
    g = StateGraph(MessagesState)
    g.add_node("agent", lambda s: s)
    g.add_edge(START, "agent")
    with pytest.raises(ValueError, match="no ToolNode"):
        lg.wrap(g, at)


def test_rejection_becomes_error_tool_message_not_exception():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate("rejected", approver="bob"), actor="ram@acme.com")
    tools = lg.wrap_tools([send_email], at, mapping=MAPPING)
    out = scripted_graph(tools, CALLS[:1]).compile().invoke({"messages": []})
    msg = [m for m in out["messages"] if isinstance(m, ToolMessage)][0]
    assert "rejected" in msg.content and at.ledger.last().confirm.status == "rejected"


def test_raise_on_block(at):
    at.gate = AutoGate("rejected")
    tools = lg.wrap_tools([send_email], at, mapping=MAPPING, raise_on_block=True)
    with pytest.raises(ActionRejected):
        tools[0].invoke({"to": "x@ext.com", "subject": "s", "body": "b"})


def test_edits_at_gate_reach_the_tool():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate("approved", edits={"subject": "EDITED"}), actor="ram@acme.com")
    seen = {}

    @tool
    def send2(to: str, subject: str) -> dict:
        """send"""
        seen["subject"] = subject
        return {"id": 1}

    lg.wrap_tools([send2], at, mapping={"send2": {"system": "gmail", "verb": "send"}})[0].invoke({"to": "x@ext.com", "subject": "orig"})
    assert seen["subject"] == "EDITED" and at.ledger.last().confirm.status == "edited"


def test_unmapped_tool_is_inferred_from_name(at):
    tools = lg.wrap_tools([send_email], at)
    tools[0].invoke({"to": "bob@acme.com", "subject": "s", "body": "b"})
    d = at.ledger.last().descriptor
    assert d["verb"] == "send" and d["system"] == "unknown" and d["source"] == "mcp"


async def test_async_tool(at):
    tools = lg.wrap_tools([async_ping], at, mapping={"async_ping": {"system": "x", "verb": "get"}})
    assert await tools[0].ainvoke({"x": 5}) == {"id": 5}
    assert at.ledger.last().verification.level == "acknowledged"


def test_read_back_through_mapping(at):
    class G:
        def users(self):
            return self
        def messages(self):
            return self
        def get(self, **kw):
            data = {"id": "m1", "labelIds": ["SENT"], "payload": {"headers": [{"name": "To", "value": "arun@newco.com"}, {"name": "Subject", "value": "Hi"}]}}
            return type("R", (), {"execute": lambda s: data})()
    m = {"send_email": {**MAPPING["send_email"], "readers": {"gmail": G()}}}
    lg.wrap_tools([send_email], at, mapping=m)[0].invoke(CALLS[0]["args"])
    assert at.ledger.last().verification.level == "verified"


class ScriptedChat:
    """Minimal chat model for create_agent: replays AIMessages, accepts bind_tools."""

    def __new__(cls, messages):
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

        class _M(GenericFakeChatModel):
            def bind_tools(self, tools, **kw):
                return self

            @property
            def profile(self):
                return {}

        return _M(messages=iter(messages))


def test_middleware_wraps_tool_calls(at):
    pytest.importorskip("langchain")
    from langchain.agents import create_agent

    model = ScriptedChat([AIMessage(content="", tool_calls=CALLS), AIMessage(content="done")])
    agent = create_agent(model, [send_email, update_deal], middleware=[lg.AttestMiddleware(at, mapping=MAPPING)])
    out = agent.invoke({"messages": [("user", "go")]})
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 2 and at.ledger.count() == 2
    # create_agent may run tool calls concurrently — assert on content, not ledger order
    by_system = {e.descriptor["system"]: e for e in at.ledger.entries()}
    assert set(by_system) == {"gmail", "hubspot"}
    e = by_system["gmail"]
    assert e.confirm.status == "approved" and e.verification.level == "acknowledged"
    assert at.ledger.verify_chain().ok


def test_middleware_rejection_returns_error_message():
    pytest.importorskip("langchain")
    from langchain.agents import create_agent

    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate("rejected"), actor="ram@acme.com")
    model = ScriptedChat([AIMessage(content="", tool_calls=CALLS[:1]), AIMessage(content="ok")])
    agent = create_agent(model, [send_email], middleware=[lg.AttestMiddleware(at, mapping=MAPPING)])
    out = agent.invoke({"messages": [("user", "go")]})
    msg = [m for m in out["messages"] if isinstance(m, ToolMessage)][0]
    assert msg.status == "error" and "rejected" in msg.content and at.ledger.last().confirm.status == "rejected"
