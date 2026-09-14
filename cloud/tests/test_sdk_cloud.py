"""SDK ⇄ cloud, end to end through the ASGI app (no network)."""
import json
import threading
import time

import pytest
from conftest import auth

from attest import ActionPending, ActionRejected, Attest
from attest.cloud import CloudClient, CloudError, CloudLedger, CloudStore, cloud_policy, refresh_policy


def transport_for(client):
    def send(method, url, body, headers):
        path = url.split("//", 1)[-1].split("/", 1)[1]
        r = client.request(method, "/" + path, content=body, headers=headers)
        try:
            return r.status_code, r.json()
        except json.JSONDecodeError:
            return r.status_code, r.text
    return send


@pytest.fixture
def cc(client, keys):
    return CloudClient("http://cloud", keys["agent"], transport=transport_for(client))


def test_client_me_and_errors(cc, client):
    assert cc.me()["key"]["role"] == "agent"
    with pytest.raises(CloudError) as ei:
        cc.request("GET", "/v1/keys")
    assert ei.value.status == 403
    with pytest.raises(ValueError):
        CloudClient("", "")


def test_cloud_ledger_pushes_and_queues(cc, client, keys):
    L = CloudLedger(cc, ":memory:")
    at = Attest(ledger=L, gate=None, actor="ram@acme.com", agent="sdk-agent")
    from attest import AutoGate
    at.gate = AutoGate()

    @at.action(system="hubspot", verb="update", target="deal_id")
    def upd(deal_id, dealname):
        return {"id": deal_id}

    upd("7", "Acme")
    assert L.pending_count() == 0 and L.last_push[0]["seq"] == 1
    remote = client.get("/v1/ledger", headers=auth(keys["agent"])).json()
    assert remote[0]["action_id"] == L.last().action_id and remote[0]["client_hash"] == L.last().hash
    assert remote[0]["params_preview"] == {"deal_id": "7", "dealname": "Acme"} and "params" not in remote[0]["descriptor"]

    # cloud goes away: entries queue locally, agent keeps working
    good = cc._send
    cc._send = lambda *a: (503, {"detail": "down"})
    upd("8", "B")
    upd("9", "C")
    assert L.pending_count() == 2 and L.count() == 3 and L.verify_chain().ok
    cc._send = good
    assert L.flush() == 2 and L.pending_count() == 0
    assert len(client.get("/v1/ledger", headers=auth(keys["agent"])).json()) == 3
    assert client.get("/v1/ledger/verify", headers=auth(keys["agent"])).json()["ok"]


def test_policy_sync_and_refresh(cc, client, keys):
    engine = cloud_policy(cc)
    assert engine.cloud_version == 1
    client.put("/v1/policy", json={"yaml": "policies:\n  - match: {verb: search}\n    decision: refuse\n"}, headers=auth(keys["admin"]))
    assert refresh_policy(engine) and engine.cloud_version == 2
    from attest.descriptor import ActionDescriptor as D
    assert engine.evaluate(D(system="x", verb="search")).decision == "refuse"
    assert not refresh_policy(engine)
    broken = CloudClient("http://cloud", "atk_bad", transport=transport_for(client))
    assert cloud_policy(broken).evaluate(D(system="x", verb="search")).decision == "act"  # fallback


def test_attest_cloud_block_mode_with_cloud_approval(client, keys):
    at = Attest.cloud("http://cloud", keys["agent"], transport=transport_for(client), wait=True, timeout_s=10, poll_s=0.05,
                      ledger_path=":memory:", actor="ram@acme.com", agent="cloud-agent")
    assert isinstance(at.store, CloudStore) and isinstance(at.ledger, CloudLedger)

    @at.action(system="gmail", verb="send", target="to")
    def send(to, subject):
        return {"id": "m1"}

    def approve():
        for _ in range(200):
            pend = client.get("/v1/confirm", headers=auth(keys["approver"])).json()
            if pend:
                client.post(f"/v1/confirm/{pend[0]['id']}/decide", json={"status": "approved", "edits": {"subject": "E"}},
                            headers=auth(keys["approver"]))
                return
            time.sleep(0.02)

    threading.Thread(target=approve).start()
    send("arun@newco.com", "orig")
    e = at.ledger.last()
    assert e.confirm.status == "edited" and e.confirm.approver == "ram" and e.confirm.channel == "cloud"
    remote = client.get("/v1/ledger", headers=auth(keys["agent"])).json()[0]
    assert remote["confirm"]["status"] == "edited" and remote["params_preview"]["subject"] == "E"


def test_attest_cloud_pending_mode_and_resume(client, keys):
    at = Attest.cloud("http://cloud", keys["agent"], transport=transport_for(client), wait=False, ledger_path=":memory:")

    @at.action(system="slack", verb="delete")
    def rm(channel):
        return {"ok": True}

    with pytest.raises(ActionPending) as ei:
        rm("C1")
    tok = ei.value.resume_token
    assert client.get(f"/v1/confirm/{tok}", headers=auth(keys["agent"])).json()["status"] == "pending"
    with pytest.raises(ActionPending):
        at.resume(tok)
    client.post(f"/v1/confirm/{tok}/decide", json={"status": "rejected", "note": "no"}, headers=auth(keys["approver"]))
    with pytest.raises(ActionRejected):
        at.resume(tok)
    assert at.ledger.last().confirm.status == "rejected"
    remote = client.get("/v1/ledger", headers=auth(keys["agent"])).json()
    assert remote[0]["confirm"]["status"] == "rejected" and remote[1]["confirm"]["status"] == "pending"


def test_cloud_store_timeout_and_unknown(cc):
    st = CloudStore(cc)
    assert st.get("nope") is None and st.decision("nope") is None
    assert st.wait("nope", timeout_s=0.1).status == "rejected"
