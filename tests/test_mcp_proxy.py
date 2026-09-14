import json
import os
import subprocess
import sys
import time

import pytest

from attest import PendingStore, SqliteLedger
from attest.gate import ConfirmDecision
from attest.mcp.proxy import result_value

FAKE = os.path.join(os.path.dirname(__file__), "mcp_fake_server.py")


class ProxyClient:
    def __init__(self, ledger_path, *extra):
        cmd = [sys.executable, "-m", "attest.mcp.proxy", "--upstream", f"{sys.executable} {FAKE}", "--server", "tracker",
               "--ledger", str(ledger_path), *extra]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
                                  env={**os.environ, "ATTEST_ACTOR": "ram@acme.com"})
        self.n = 0

    def call(self, method, params=None, timeout=15):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("proxy closed")
            msg = json.loads(line)
            if msg.get("id") == self.n:
                return msg
        raise TimeoutError

    def tool(self, name, args):
        return self.call("tools/call", {"name": name, "arguments": args})["result"]

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=5)


def payload(res):
    return json.loads(res["content"][0]["text"])


@pytest.fixture
def auto(tmp_path):
    c = ProxyClient(tmp_path / "l.sqlite", "--mode", "auto")
    yield c, tmp_path / "l.sqlite"
    c.close()


def test_initialize_and_tools_list_adds_resume(auto):
    c, _ = auto
    assert c.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})["result"]["serverInfo"]["name"] == "fake"
    names = [t["name"] for t in c.call("tools/list")["result"]["tools"]]
    assert names[-1] == "attest_resume" and "create_issue" in names


def test_create_is_verified_by_tool_pair_read_back(auto):
    c, path = auto
    c.call("tools/list")
    res = c.tool("create_issue", {"title": "Hello"})
    assert payload(res)["id"] == "I-1" and res["_attest"]["level"] == "verified"
    e = SqliteLedger(path).last()
    d = e.descriptor
    assert (d["system"], d["verb"], d["extra"]["tool_name"]) == ("tracker", "create", "create_issue")
    assert e.verification.method == "read-back:mcp-pair" and e.verification.evidence["fields"]["title"]["ok"]
    assert e.actor == "ram@acme.com" and e.agent == "mcp-client"


def test_update_contradiction_is_unverified(auto):
    c, path = auto
    c.call("tools/list")
    c.tool("create_issue", {"title": "A"})
    res = c.tool("update_issue", {"issue_id": "I-1", "title": "LOSE-IT"})
    assert res["_attest"]["level"] == "unverified"
    assert SqliteLedger(path).last().verification.evidence["failed"] == ["title"]


def test_reads_pass_through_and_errors_are_recorded(auto):
    c, path = auto
    c.call("tools/list")
    res = c.tool("list_issues", {})
    assert payload(res) == [] and res["_attest"]["level"] == "attested-only"
    res = c.tool("get_issue", {"issue_id": "nope"})
    assert res["isError"] and "not found" in res["content"][0]["text"]
    assert SqliteLedger(path).last().execution.status == "failed"


def test_pending_mode_then_resume(tmp_path):
    path = tmp_path / "l.sqlite"
    c = ProxyClient(path, "--mode", "pending")
    try:
        c.call("tools/list")
        res = c.tool("create_issue", {"title": "Needs approval"})
        out = payload(res)
        assert out["status"] == "pending_confirmation" and out["action"] == "tracker.create:issue"
        tok = out["resume_token"]
        assert SqliteLedger(path).last().confirm.status == "pending"
        still = payload(c.tool("attest_resume", {"resume_token": tok}))
        assert still["status"] == "pending_confirmation"
        PendingStore(path).decide(tok, ConfirmDecision("edited", "ram", {"title": "Approved title"}, channel="cli"))
        res = c.tool("attest_resume", {"resume_token": tok})
        assert payload(res)["title"] == "Approved title" and res["_attest"]["level"] == "verified"
        e = SqliteLedger(path).last()
        assert e.confirm.status == "edited" and e.confirm.approver == "ram" and e.resumed_from
        assert c.tool("attest_resume", {"resume_token": "nope"})["isError"]
    finally:
        c.close()


def test_pending_rejected(tmp_path):
    path = tmp_path / "l.sqlite"
    c = ProxyClient(path, "--mode", "pending")
    try:
        c.call("tools/list")
        tok = payload(c.tool("delete_issue", {"issue_id": "I-1"}))["resume_token"]
        PendingStore(path).decide(tok, ConfirmDecision("rejected", "bob"))
        res = c.tool("attest_resume", {"resume_token": tok})
        assert res["isError"] and "rejected" in res["content"][0]["text"]
    finally:
        c.close()


def test_block_mode_waits_for_store_decision(tmp_path):
    path = tmp_path / "l.sqlite"
    c = ProxyClient(path, "--mode", "block", "--timeout", "10")
    try:
        c.call("tools/list")
        import threading

        def approve():
            store = PendingStore(path)
            for _ in range(100):
                pend = store.pending()
                if pend:
                    store.decide(pend[0]["id"], ConfirmDecision("approved", "web-ram", channel="web"))
                    return
                time.sleep(0.05)

        threading.Thread(target=approve).start()
        res = c.tool("create_issue", {"title": "Blocking"})
        assert payload(res)["id"] == "I-1" and res["_attest"]["level"] == "verified"
        assert SqliteLedger(path).last().confirm.approver == "web-ram"
    finally:
        c.close()


def test_result_value_parsing():
    assert result_value({"content": [{"type": "text", "text": '{"id": 1}'}]}) == {"id": 1}
    assert result_value({"structuredContent": {"id": 2}, "content": []}) == {"id": 2}
    assert result_value({"content": [{"type": "text", "text": "plain"}]}) == "plain"
    assert result_value({"isError": True, "content": [{"type": "text", "text": "boom"}]}) == {"error": "boom"}
    assert result_value("x") == "x"
