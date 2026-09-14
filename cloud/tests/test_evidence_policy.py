"""P2.2 / P2.3 on the cloud: approver-group enforcement, checkpoints, retention prune, IETF + EU AI Act exports."""
import json

from conftest import auth
from test_api import confirm_body, entry

GROUPED = """
policies:
  - match: { verb: [delete, pay] }
    decision: ask
    approvers: [finance-leads]
groups:
  finance-leads: [ram, priya@acme.com]
agents:
  bot@v1:
    policies:
      - match: { verb: delete }
        decision: act
"""


def test_policy_put_accepts_groups_and_agents_and_decide_uses_overrides(client, keys):
    r = client.put("/v1/policy", json={"yaml": GROUPED}, headers=auth(keys["admin"])).json()
    assert r["groups"] == 1 and r["agents"] == 1
    d = client.post("/v1/decide", json={"descriptor": {"system": "x", "verb": "delete", "agent": "bot@v1"}},
                    headers=auth(keys["agent"])).json()
    assert d["decision"] == "act"
    d = client.post("/v1/decide", json={"descriptor": {"system": "x", "verb": "delete", "agent": "other"}},
                    headers=auth(keys["agent"])).json()
    assert d["decision"] == "ask" and d["approver_members"] == ["ram", "priya@acme.com"]


def test_confirm_decide_enforces_group_membership(client, keys):
    client.put("/v1/policy", json={"yaml": GROUPED}, headers=auth(keys["admin"]))
    outsider = client.post("/v1/keys", json={"name": "bob", "role": "approver"}, headers=auth(keys["admin"])).json()["api_key"]
    # SDK sends group names only ⇒ cloud resolves members from the org policy
    r = client.post("/v1/confirm", json=confirm_body(id="cfm_g", approvers=["finance-leads"]), headers=auth(keys["agent"])).json()
    assert r["approver_members"] == ["ram", "priya@acme.com"]
    denied = client.post("/v1/confirm/cfm_g/decide", json={"status": "approved"}, headers=auth(outsider))
    assert denied.status_code == 403 and "finance-leads" in denied.text or "ram" in denied.text
    ok = client.post("/v1/confirm/cfm_g/decide", json={"status": "approved"}, headers=auth(keys["approver"]))  # key name "ram"
    assert ok.status_code == 200 and ok.json()["approver"] == "ram"
    # admins may always decide
    client.post("/v1/confirm", json=confirm_body(id="cfm_h", approvers=["finance-leads"]), headers=auth(keys["agent"]))
    assert client.post("/v1/confirm/cfm_h/decide", json={"status": "rejected"}, headers=auth(keys["admin"])).status_code == 200


def test_checkpoint_and_prune_keep_chain_verifiable(client, keys, monkeypatch):
    monkeypatch.setenv("ATTEST_SIGNING_KEY", "server-key")
    assert client.post("/v1/ledger/checkpoint", headers=auth(keys["admin"])).status_code == 409  # empty
    client.post("/v1/attest", json={"entries": [entry(i) for i in range(1, 7)]}, headers=auth(keys["agent"]))
    cp = client.post("/v1/ledger/checkpoint", headers=auth(keys["admin"])).json()
    assert cp["seq"] == 6 and cp["signature"].startswith("v1=") and cp["scope"] == "org:acme" and cp["reason"] == "manual"
    assert client.post("/v1/ledger/checkpoint", headers=auth(keys["agent"])).status_code == 403
    out = client.post("/v1/ledger/prune", json={"before_seq": 4}, headers=auth(keys["admin"])).json()
    assert out == {"removed": 3, "chain_ok": True, "entries": 6}
    cps = client.get("/v1/ledger/checkpoints", headers=auth(keys["agent"])).json()
    assert [c["seq"] for c in cps] == [3, 6] and cps[0]["reason"] == "retention"
    rows = client.get("/v1/ledger", headers=auth(keys["agent"])).json()
    assert [r["seq"] for r in rows] == [6, 5, 4]
    assert client.get("/v1/ledger/verify", headers=auth(keys["agent"])).json()["ok"]
    # prune by the org retention setting (everything older than now-ish stays: nothing is a day old)
    assert client.post("/v1/ledger/prune", json={}, headers=auth(keys["admin"])).status_code == 422
    client.put("/v1/settings", json={"retention_days": 30}, headers=auth(keys["admin"]))
    assert client.post("/v1/ledger/prune", json={}, headers=auth(keys["admin"])).json()["removed"] == 0


def test_export_ietf_and_eu_ai_act(client, keys, monkeypatch):
    monkeypatch.setenv("ATTEST_SIGNING_KEY", "server-key")
    client.post("/v1/attest", json={"entries": [entry(1), entry(2)]}, headers=auth(keys["agent"]))
    client.post("/v1/ledger/checkpoint", headers=auth(keys["admin"]))
    r = client.get("/v1/export?format=ietf", headers=auth(keys["agent"]))
    assert r.headers["content-type"].startswith("application/x-ndjson")
    recs = [json.loads(line) for line in r.text.splitlines()]
    assert len(recs) == 2 and recs[1]["parent_record_id"] == recs[0]["record_id"] and recs[0]["agent_id"] == "urn:attest:agent:a1"
    pack = client.get("/v1/export?format=eu-ai-act", headers=auth(keys["agent"])).json()
    assert pack["system"]["org"] == "acme" and pack["period"]["events"] == 2
    assert pack["integrity"]["checkpoints"][0]["seq"] == 2 and pack["integrity"]["chain"]["ok"]
    assert pack["manifest"]["signature"].startswith("v1=") and pack["manifest"]["scope"] == "org:acme"
