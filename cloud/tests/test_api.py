import hashlib
import hmac
import json
import time
import urllib.parse

from conftest import auth

from attest.descriptor import ActionDescriptor as D
from attest.ledger import LedgerEntry


def entry(i=0, agent="a1", **kw):
    d = D(system="gmail", verb="send", target=f"u{i}@ext.com", params={"to": f"u{i}@ext.com", "body": "secret"}, agent=agent,
          run_id="r1", actor="ram@acme.com")
    e = LedgerEntry.from_descriptor(d, decision="ask", risk_tier="high", **kw)
    return {**e.payload(), "seq": i + 1, "hash": "f" * 64}


# ── tenancy ──────────────────────────────────────────────────────────────────
def test_bootstrap_requires_token_and_slug_unique(client):
    assert client.post("/v1/orgs", json={"name": "X"}).status_code == 401
    r = client.post("/v1/orgs", json={"name": "Acme Inc"}, headers={"X-Bootstrap-Token": "boot"})
    assert r.status_code == 201 and r.json()["org"]["slug"] == "acme-inc" and r.json()["api_key"].startswith("atk_")
    assert client.post("/v1/orgs", json={"name": "Acme Inc"}, headers={"X-Bootstrap-Token": "boot"}).status_code == 409


def test_auth_and_roles(client, keys):
    assert client.get("/v1/me").status_code == 401
    assert client.get("/v1/me", headers=auth("atk_nope")).status_code == 401
    me = client.get("/v1/me", headers=auth(keys["agent"])).json()
    assert me["key"]["role"] == "agent" and me["org"]["name"] == "Acme"
    assert client.get("/v1/keys", headers=auth(keys["agent"])).status_code == 403
    assert client.get("/v1/keys", headers=auth(keys["approver"])).status_code == 403
    listed = client.get("/v1/keys", headers=auth(keys["admin"])).json()
    assert [k["role"] for k in listed] == ["admin", "agent", "approver"] and "api_key" not in listed[0]


def test_revoke_key(client, keys):
    kid = [k for k in client.get("/v1/keys", headers=auth(keys["admin"])).json() if k["role"] == "agent"][0]["id"]
    assert client.delete(f"/v1/keys/{kid}", headers=auth(keys["admin"])).status_code == 200
    assert client.get("/v1/me", headers=auth(keys["agent"])).status_code == 401
    me_id = client.get("/v1/me", headers=auth(keys["admin"])).json()["key"]["id"]
    assert client.delete(f"/v1/keys/{me_id}", headers=auth(keys["admin"])).status_code == 400


def test_org_isolation(client, keys):
    other = client.post("/v1/orgs", json={"name": "Other"}, headers={"X-Bootstrap-Token": "boot"}).json()["api_key"]
    client.post("/v1/attest", json={"entries": [entry(1)]}, headers=auth(keys["agent"]))
    client.post("/v1/attest", json={"entries": [entry(2, agent="b")]}, headers=auth(other))
    mine = client.get("/v1/ledger", headers=auth(keys["agent"])).json()
    theirs = client.get("/v1/ledger", headers=auth(other)).json()
    assert len(mine) == 1 and len(theirs) == 1 and mine[0]["seq"] == 1 and theirs[0]["seq"] == 1
    assert client.get(f"/v1/ledger/{mine[0]['action_id']}", headers=auth(other)).status_code == 404
    assert client.get("/v1/agents", headers=auth(other)).json()[0]["name"] == "b"


# ── ledger ───────────────────────────────────────────────────────────────────
def test_sink_chains_per_org_and_is_idempotent(client, keys):
    e1, e2 = entry(1), entry(2)
    out = client.post("/v1/attest", json={"entries": [e1, e2]}, headers=auth(keys["agent"])).json()
    assert [o["seq"] for o in out] == [1, 2]
    again = client.post("/v1/attest", json={"entry": e1}, headers=auth(keys["agent"])).json()
    assert again[0]["seq"] == 1 and again[0]["hash"] == out[0]["hash"]
    rows = client.get("/v1/ledger", headers=auth(keys["agent"])).json()
    assert [r["seq"] for r in rows] == [2, 1] and rows[1]["client_seq"] == 2 and rows[1]["client_hash"] == "f" * 64
    assert rows[0]["prev_hash"] == out[0]["hash"]
    rep = client.get("/v1/ledger/verify", headers=auth(keys["agent"])).json()
    assert rep["ok"] and rep["checked"] == 2
    stats = client.get("/v1/ledger/stats", headers=auth(keys["agent"])).json()
    assert stats["total"] == 2 and stats["by_decision"] == {"ask": 2}
    agents = client.get("/v1/agents", headers=auth(keys["agent"])).json()
    assert agents[0]["name"] == "a1" and agents[0]["actions"] == 2


def test_sink_rejects_raw_params(client, keys):
    bad = entry(1)
    bad["descriptor"]["params"] = {"body": "secret"}
    r = client.post("/v1/attest", json={"entry": bad}, headers=auth(keys["agent"]))
    assert r.status_code == 422 and "raw params" in r.text
    assert client.post("/v1/attest", json={}, headers=auth(keys["agent"])).status_code == 422


def test_ledger_filters_and_action_lookup(client, keys):
    client.post("/v1/attest", json={"entries": [entry(1), entry(2, agent="other")]}, headers=auth(keys["agent"]))
    assert len(client.get("/v1/ledger?agent=other", headers=auth(keys["agent"])).json()) == 1
    assert len(client.get("/v1/ledger?level=verified", headers=auth(keys["agent"])).json()) == 0
    assert len(client.get("/v1/ledger?before_seq=2", headers=auth(keys["agent"])).json()) == 1
    aid = client.get("/v1/ledger", headers=auth(keys["agent"])).json()[0]["action_id"]
    assert client.get(f"/v1/ledger/{aid}", headers=auth(keys["agent"])).json()[0]["action_id"] == aid


def test_tamper_detected(client, keys, db):
    client.post("/v1/attest", json={"entries": [entry(1), entry(2)]}, headers=auth(keys["agent"]))
    from attest_cloud.db import LedgerRow
    from sqlalchemy import select
    with db.session() as s:
        row = s.scalar(select(LedgerRow).where(LedgerRow.seq == 1))
        row.payload = {**row.payload, "decision": "act"}
    rep = client.get("/v1/ledger/verify", headers=auth(keys["agent"])).json()
    assert not rep["ok"] and rep["broken_at"] == 1


def test_export_json_and_csv(client, keys):
    client.post("/v1/attest", json={"entries": [entry(1)]}, headers=auth(keys["agent"]))
    j = client.get("/v1/export", headers=auth(keys["agent"])).json()
    assert j["manifest"]["entries"] == 1 and j["manifest"]["chain"]["ok"] and j["entries"][0]["seq"] == 1
    c = client.get("/v1/export?format=csv", headers=auth(keys["agent"]))
    assert c.headers["content-type"].startswith("text/csv") and c.text.splitlines()[0].startswith("seq,")


# ── policy ───────────────────────────────────────────────────────────────────
def test_policy_default_versioning_and_decide(client, keys):
    p = client.get("/v1/policy", headers=auth(keys["agent"])).json()
    assert p["version"] == 1 and "external-send" in p["yaml"]
    bad = client.put("/v1/policy", json={"yaml": "policies:\n  - match: {colour: red}\n    decision: act\n"}, headers=auth(keys["admin"]))
    assert bad.status_code == 422
    assert client.put("/v1/policy", json={"yaml": "policies: []"}, headers=auth(keys["agent"])).status_code == 403
    ok = client.put("/v1/policy", json={"yaml": "policies:\n  - match: {verb: send}\n    decision: refuse\n"}, headers=auth(keys["admin"])).json()
    assert ok["version"] == 2 and ok["rules"] == 1
    versions = client.get("/v1/policy/versions", headers=auth(keys["agent"])).json()
    assert [(v["version"], v["active"]) for v in versions] == [(2, True), (1, False)]
    dec = client.post("/v1/decide", json={"descriptor": {"system": "gmail", "verb": "send", "params": {"to": "x@acme.com"}}},
                      headers=auth(keys["agent"])).json()
    assert dec["decision"] == "refuse" and dec["policy_version"] == 2 and dec["target_class"] == "internal"
    assert client.post("/v1/decide", json={"descriptor": {"verb": "nope"}}, headers=auth(keys["agent"])).status_code == 422


# ── confirm ──────────────────────────────────────────────────────────────────
def confirm_body(**kw):
    d = D(system="gmail", verb="send", target="x@ext.com", params={"to": "x@ext.com", "subject": "S"})
    return {"action_id": d.id, "descriptor": d.model_dump(mode="json"), "reasons": ["external"], "risk_tier": "high", **kw}


def test_confirm_lifecycle(client, keys):
    r = client.post("/v1/confirm", json=confirm_body(id="cfm_1", resume_token="rsm_1"), headers=auth(keys["agent"]))
    assert r.status_code == 201 and r.json()["status"] == "pending" and r.json()["channel"] == "cloud"
    assert client.post("/v1/confirm", json=confirm_body(id="cfm_1", resume_token="rsm_1"), headers=auth(keys["agent"])).json()["id"] == "cfm_1"
    assert [x["id"] for x in client.get("/v1/confirm", headers=auth(keys["agent"])).json()] == ["cfm_1"]
    assert client.get("/v1/confirm/rsm_1", headers=auth(keys["agent"])).json()["id"] == "cfm_1"
    assert client.post("/v1/confirm/cfm_1/decide", json={"status": "approved"}, headers=auth(keys["agent"])).status_code == 403
    out = client.post("/v1/confirm/cfm_1/decide", json={"status": "approved", "edits": {"subject": "E"}}, headers=auth(keys["approver"])).json()
    assert out["status"] == "edited" and out["approver"] == "ram" and out["edits"] == {"subject": "E"}
    assert client.post("/v1/confirm/cfm_1/decide", json={"status": "rejected"}, headers=auth(keys["approver"])).status_code == 409
    assert client.post("/v1/confirm/nope/decide", json={"status": "rejected"}, headers=auth(keys["approver"])).status_code == 404
    assert client.get("/v1/confirm?status=all", headers=auth(keys["agent"])).json()[0]["status"] == "edited"
    assert client.get("/v1/confirm", headers=auth(keys["agent"])).json() == []


def test_confirm_ttl_expires(client, keys):
    client.post("/v1/confirm", json=confirm_body(id="cfm_2", ttl_s=-1), headers=auth(keys["agent"]))
    assert client.get("/v1/confirm/cfm_2", headers=auth(keys["agent"])).json()["status"] == "expired"


def test_slack_interact_resolves_org_and_verifies_signature(client, keys):
    client.put("/v1/settings", json={"slack_signing_secret": "ss"}, headers=auth(keys["admin"]))
    client.post("/v1/confirm", json=confirm_body(id="cfm_3"), headers=auth(keys["agent"]))
    payload = {"type": "block_actions", "user": {"id": "U1", "username": "ram"},
               "actions": [{"action_id": "attest_approve", "value": "cfm_3"}]}
    body = urllib.parse.urlencode({"payload": json.dumps(payload)}).encode()
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(b"ss", f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()
    bad = client.post("/slack/interact", content=body, headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": "v0=bad",
                                                                 "Content-Type": "application/x-www-form-urlencoded"})
    assert bad.status_code == 401
    ok = client.post("/slack/interact", content=body, headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig,
                                                                "Content-Type": "application/x-www-form-urlencoded"})
    assert ok.status_code == 200 and ok.json()["decision"]["status"] == "approved"
    assert client.get("/v1/confirm/cfm_3", headers=auth(keys["agent"])).json()["approver"] == "ram (U1)"


def test_settings_masking(client, keys):
    r = client.put("/v1/settings", json={"domain": "acme.io", "slack_bot_token": "xoxb-secret-token", "slack_channel": "C1"},
                   headers=auth(keys["admin"])).json()
    assert r["domain"] == "acme.io" and r["slack_bot_token"] == "xoxb-s…" and r["slack_channel"] == "C1"
    assert client.get("/v1/settings", headers=auth(keys["agent"])).status_code == 403
    dec = client.post("/v1/decide", json={"descriptor": {"system": "gmail", "verb": "send", "params": {"to": "x@acme.io"}}},
                      headers=auth(keys["agent"])).json()
    assert dec["target_class"] == "internal"


def test_healthz(client):
    assert client.get("/healthz").json()["ok"] is True
