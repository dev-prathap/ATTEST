"""Demo 2 (M1) — a LangGraph agent sends an email and updates a CRM deal; both land in the ledger as
`verified` with read-back evidence.

Zero-config: runs with in-memory Gmail and HubSpot fakes shaped like the real clients, and a scripted
"model" so no LLM key is needed. Point it at real systems by setting:

    ATTEST_LIVE_GMAIL_TOKEN, ATTEST_LIVE_GMAIL_TO, ATTEST_LIVE_HUBSPOT_TOKEN

Run:   ATTEST_AUTO_APPROVE=1 python examples/langgraph_agent.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langgraph.graph import END, START, MessagesState, StateGraph  # noqa: E402
from langgraph.prebuilt import ToolNode  # noqa: E402

from attest import Attest, SqliteLedger  # noqa: E402
from attest.adapters import langgraph as attest_lg  # noqa: E402

GMAIL_TOKEN = os.environ.get("ATTEST_LIVE_GMAIL_TOKEN")
HUBSPOT_TOKEN = os.environ.get("ATTEST_LIVE_HUBSPOT_TOKEN")
LIVE = bool(GMAIL_TOKEN and HUBSPOT_TOKEN)


# ── fakes shaped like the real vendor clients (used when no tokens are set) ─────────────────────
class FakeGmailService:
    """Looks like googleapiclient's Gmail resource: users().messages().send()/get()."""

    def __init__(self):
        self.store: dict[str, dict] = {}

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):
        raw = base64.urlsafe_b64decode(body["raw"]).decode()
        headers = dict(line.split(": ", 1) for line in raw.split("\r\n\r\n")[0].split("\r\n"))
        mid = f"m{len(self.store) + 1}"
        self.store[mid] = {"id": mid, "threadId": f"t{mid}", "labelIds": ["SENT"],
                           "payload": {"headers": [{"name": k, "value": v} for k, v in headers.items()]}}
        return _Exec({"id": mid, "threadId": f"t{mid}"})

    def get(self, userId, id, format=None, metadataHeaders=None):
        return _Exec(self.store[id])


class FakeHubSpot:
    """Looks like hubspot-api-client: crm.objects.basic_api.get_by_id()."""

    def __init__(self):
        self.store: dict[tuple[str, str], dict] = {("deals", "777"): {"dealname": "Acme", "dealstage": "qualified"}}
        self.crm = self

    @property
    def objects(self):
        return self

    @property
    def basic_api(self):
        return self

    def get_by_id(self, object_type, object_id, properties=None):
        return {"id": object_id, "properties": dict(self.store[(object_type, object_id)])}

    def patch(self, object_type, object_id, properties):
        self.store[(object_type, object_id)].update(properties)
        return {"id": object_id, "properties": properties}


class _Exec:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return self.data


gmail = FakeGmailService()
hubspot = FakeHubSpot()


# ── the agent's tools — plain LangChain tools, nothing Attest-specific inside ──────────────────
@tool
def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email through Gmail."""
    raw = base64.urlsafe_b64encode(f"To: {to}\r\nSubject: {subject}\r\n\r\n{body}".encode()).decode()
    if LIVE:
        req = urllib.request.Request("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                                     data=json.dumps({"raw": raw}).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {GMAIL_TOKEN}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    return gmail.users().messages().send(userId="me", body={"raw": raw}).execute()


@tool
def update_deal(deal_id: str, properties: dict) -> dict:
    """Update properties on a HubSpot deal."""
    if LIVE:
        req = urllib.request.Request(f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}",
                                     data=json.dumps({"properties": properties}).encode(), method="PATCH",
                                     headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    return hubspot.patch("deals", deal_id, properties)


# ── one line: wrap the tools ───────────────────────────────────────────────────────────────────
at = Attest(ledger=SqliteLedger(":memory:"), agent="followup-agent@v3", actor="ram@acme.com",
            readers={"gmail": GMAIL_TOKEN or gmail, "hubspot": HUBSPOT_TOKEN or hubspot})
tools = attest_lg.wrap_tools([send_email, update_deal], at, mapping={
    "send_email": {"system": "gmail", "verb": "send", "target": "to"},
    "update_deal": {"system": "hubspot", "verb": "update", "target": "deal_id"},
})

# ── a LangGraph agent. The "model" is scripted so the demo needs no LLM key; swap in create_react_agent. ──
TO = os.environ.get("ATTEST_LIVE_GMAIL_TO", "arun@newco.com")
DEAL = os.environ.get("ATTEST_LIVE_HUBSPOT_DEAL", "777")
PLAN = [
    {"name": "send_email", "id": "c1", "args": {"to": TO, "subject": "Following up on our call",
                                              "body": "Hi Arun — sending the proposal we discussed."}},
    {"name": "update_deal", "id": "c2", "args": {"deal_id": DEAL, "properties": {"dealstage": "proposal_sent"}}},
]
graph = StateGraph(MessagesState)
graph.add_node("agent", lambda s: {"messages": [AIMessage(content="", tool_calls=PLAN)]})
graph.add_node("tools", ToolNode(tools))
graph.add_edge(START, "agent")
graph.add_edge("agent", "tools")
graph.add_edge("tools", END)
app = graph.compile()

if __name__ == "__main__":
    print(f"mode: {'LIVE' if LIVE else 'fakes'}")
    with at.run("demo-langgraph"):
        out = app.invoke({"messages": []})
    for m in out["messages"]:
        if isinstance(m, ToolMessage):
            print(f"tool {m.name}: {m.content[:80]}")
    print("\n── ledger ──")
    for e in at.ledger.entries():
        d = e.descriptor
        print(f"#{e.seq} {d['system']}.{d['verb']} → {d['target']}  decision={e.decision} confirm={e.confirm.status} "
              f"level={e.verification.level}  method={e.verification.method}")
        print("    evidence:", json.dumps(e.verification.evidence.get("fields") or e.verification.evidence))
    rep = at.ledger.verify_chain()
    print(f"chain: ok={rep.ok} entries={rep.checked}")
    levels = [e.verification.level for e in at.ledger.entries()]
    print("M1:", "PASS — two verified entries" if levels == ["verified", "verified"] else f"not yet: {levels}")
