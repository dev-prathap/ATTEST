import json
import os
import subprocess
import sys

from attest import Attest, AutoGate, PendingStore, SqliteLedger, StoreGate
from attest.gate import ConfirmDecision
from attest.mcp.server import TOOLS, Server


def text(res):
    return json.loads(res["content"][0]["text"])


def test_tools_and_decide_record_ledger():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), actor="ram@acme.com", agent="mcp")
    s = Server(at)
    assert [t["name"] for t in TOOLS] == ["attest_decide", "attest_confirm", "attest_confirm_status", "attest_record",
                                           "attest_verify", "attest_ledger"]
    d = text(s.call("attest_decide", {"system": "gmail", "verb": "send", "params": {"to": "x@ext.com"}}))
    assert d["decision"] == "ask" and d["target_class"] == "external" and d["action"] == "gmail.send"
    r = text(s.call("attest_record", {"system": "n8n", "verb": "send", "result": {"id": "m1"}}))
    assert r["level"] == "acknowledged" and r["seq"] == 1
    r = text(s.call("attest_record", {"system": "n8n", "verb": "send", "verified": False, "evidence": {"why": "bounced"}}))
    assert r["level"] == "unverified"
    lg = text(s.call("attest_ledger", {"verify_chain": True, "limit": 5}))
    assert len(lg["entries"]) == 2 and lg["chain"]["ok"]
    assert s.call("attest_nope", {})["isError"]


def test_confirm_wait_and_status():
    store = PendingStore(":memory:")
    at = Attest(ledger=SqliteLedger(":memory:"), gate=StoreGate(store, wait=False), store=store)
    s = Server(at)
    out = text(s.call("attest_confirm", {"system": "slack", "verb": "delete", "params": {"channel": "C1"}}))
    assert out["status"] == "pending" and store.get(out["request_id"])["status"] == "pending"
    assert text(s.call("attest_confirm_status", {"request_id": out["resume_token"]}))["status"] == "pending"
    store.decide(out["request_id"], ConfirmDecision("approved", "ram"))
    assert text(s.call("attest_confirm_status", {"request_id": out["request_id"]}))["approver"] == "ram"
    import threading
    def approve():
        for _ in range(100):
            p = store.pending()
            if p:
                store.decide(p[0]["id"], ConfirmDecision("rejected", "bob"))
                return
            import time
            time.sleep(0.02)
    threading.Thread(target=approve).start()
    out = text(s.call("attest_confirm", {"system": "slack", "verb": "delete", "wait": True, "timeout_s": 5}))
    assert out["status"] == "rejected" and out["approver"] == "bob"


def test_verify_tool_with_reader():
    class G:
        def users(self):
            return self
        def messages(self):
            return self
        def get(self, **kw):
            data = {"id": "m1", "labelIds": ["SENT"], "payload": {"headers": [{"name": "To", "value": "a@x.com"}]}}
            return type("R", (), {"execute": lambda s: data})()
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), readers={"gmail": G()})
    s = Server(at)
    out = text(s.call("attest_verify", {"system": "gmail", "verb": "send", "params": {"to": "a@x.com"}, "result": {"id": "m1"}}))
    assert out["level"] == "verified" and out["read_back_available"]
    out = text(s.call("attest_verify", {"system": "slack", "verb": "send", "params": {}, "result": {"ts": "1"}}))
    assert out["level"] == "acknowledged" and not out["read_back_available"]


def test_stdio_roundtrip(tmp_path):
    env = {**os.environ, "ATTEST_LEDGER": str(tmp_path / "l.sqlite"), "ATTEST_AUTO_APPROVE": "1"}
    p = subprocess.Popen([sys.executable, "-m", "attest.mcp.server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "attest_record", "arguments": {"system": "x", "verb": "create", "result": {"id": 1}}}},
            {"jsonrpc": "2.0", "id": 4, "method": "bogus"}]
    out, _ = p.communicate("\n".join(json.dumps(m) for m in msgs) + "\n", timeout=30)
    resps = {r["id"]: r for r in (json.loads(line) for line in out.splitlines())}
    assert resps[1]["result"]["serverInfo"]["name"] == "attest"
    assert len(resps[2]["result"]["tools"]) == 6
    assert text(resps[3]["result"])["level"] == "acknowledged"
    assert resps[4]["error"]["code"] == -32601
    assert SqliteLedger(tmp_path / "l.sqlite").count() == 1


def test_every_tool_declares_all_four_behaviour_hints():
    """Hosts warn a user from these, and directories reject tools that omit them. A missing hint is
    not a neutral default: it leaves the host guessing about a tool that may write or reach out."""
    required = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
    for t in TOOLS:
        ann = t.get("annotations")
        assert ann, f"{t['name']} declares no annotations"
        assert ann.get("title"), f"{t['name']} has no title"
        for hint in required:
            assert isinstance(ann.get(hint), bool), f"{t['name']}.{hint} must be an explicit bool"


def test_hints_match_what_the_handlers_actually_do():
    """The honesty rule applied to our own metadata: a tool that writes must not claim readOnly, and
    one that touches a third-party system must admit openWorld."""
    by_name = {t["name"]: t["annotations"] for t in TOOLS}

    # attest_confirm creates a pending request and notifies Slack / a webhook.
    assert by_name["attest_confirm"]["readOnlyHint"] is False
    assert by_name["attest_confirm"]["openWorldHint"] is True
    # attest_record appends a ledger row.
    assert by_name["attest_record"]["readOnlyHint"] is False
    # attest_verify reads the third-party system of record and writes nothing.
    assert by_name["attest_verify"]["readOnlyHint"] is True
    assert by_name["attest_verify"]["openWorldHint"] is True
    # Pure reads stay closed and repeatable.
    for name in ("attest_decide", "attest_confirm_status", "attest_ledger"):
        assert by_name[name]["readOnlyHint"] is True
        assert by_name[name]["idempotentHint"] is True
        assert by_name[name]["openWorldHint"] is False
    # The ledger is append-only and confirmations are superseded, never deleted.
    assert all(a["destructiveHint"] is False for a in by_name.values())


def test_tools_list_response_carries_the_annotations():
    srv = Server(Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate("approved")))
    res = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    tools = res["result"]["tools"]
    assert tools and all("annotations" in t for t in tools)
