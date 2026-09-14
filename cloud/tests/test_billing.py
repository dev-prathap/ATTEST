import hashlib
import hmac
import json
import time

from attest_cloud import billing
from conftest import auth
from test_api import entry


def _sig(secret, body, ts=None):
    ts = ts or str(int(time.time()))
    return f"t={ts},v1=" + hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()


def free(client, keys):
    client.put("/v1/billing/plan", json={"plan": "free"}, headers={**auth(keys["admin"]), "X-Bootstrap-Token": "boot"})


def test_billing_summary_and_free_plan_gates(client, keys):
    free(client, keys)
    b = client.get("/v1/billing", headers=auth(keys["agent"])).json()
    assert b["plan"] == "free" and b["limits"]["agents"] == 1 and b["verified_remaining"] == 100
    client.post("/v1/attest", json={"entries": [entry(1, agent="a1")]}, headers=auth(keys["agent"]))
    r = client.post("/v1/attest", json={"entries": [entry(2, agent="a2")]}, headers=auth(keys["agent"]))
    assert r.status_code == 402 and "allows 1 agent" in r.text
    assert client.post("/v1/agents", json={"name": "a3"}, headers=auth(keys["admin"])).status_code == 402
    assert client.get("/v1/export?format=ietf", headers=auth(keys["agent"])).status_code == 402
    assert client.put("/v1/settings", json={"retention_days": 90}, headers=auth(keys["admin"])).status_code == 402
    assert client.put("/v1/settings", json={"retention_days": 7}, headers=auth(keys["admin"])).status_code == 200


def test_operator_plan_override_lifts_gates(client, keys):
    free(client, keys)
    r = client.put("/v1/billing/plan", json={"plan": "pro"}, headers=auth(keys["admin"]))
    assert r.status_code == 403
    r = client.put("/v1/billing/plan", json={"plan": "pro"}, headers={**auth(keys["admin"]), "X-Bootstrap-Token": "boot"})
    assert r.status_code == 200 and r.json()["limits"]["agents"] is None
    client.post("/v1/attest", json={"entries": [entry(1, agent="a1"), entry(2, agent="a2")]}, headers=auth(keys["agent"]))
    assert client.get("/v1/export?format=ietf", headers=auth(keys["agent"])).status_code == 200
    assert client.put("/v1/settings", json={"retention_days": 365}, headers=auth(keys["admin"])).status_code == 200
    assert client.get("/v1/settings", headers=auth(keys["admin"])).json()["plan"] == "pro"
    r = client.put("/v1/billing/plan", json={"plan": "enterprise", "overrides": {"verified_actions": 5}},
                   headers={**auth(keys["admin"]), "X-Bootstrap-Token": "boot"})
    assert r.json()["limits"]["verified_actions"] == 5


def test_usage_counts_verified_levels_only(client, keys, db):
    free(client, keys)
    e1, e2 = entry(1), entry(2)
    e1["verification"] = {"level": "verified", "evidence": {}}
    client.post("/v1/attest", json={"entries": [e1, e2]}, headers=auth(keys["agent"]))
    u = client.get("/v1/billing", headers=auth(keys["agent"])).json()["usage"]
    assert u["verified_actions"] == 1 and u["actions"] == 2 and u["agents"] == 1
    from attest_cloud.db import Org
    with db.session() as s:
        org = s.scalar(__import__("sqlalchemy").select(Org))
        assert billing.check_verified_allowance(s, org, 99).ok and not billing.check_verified_allowance(s, org, 100).ok


def test_stripe_webhook_signature_and_plan_changes(client, keys, monkeypatch, org):
    free(client, keys)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec")
    monkeypatch.setenv("STRIPE_PRICE_TEAM", "price_team")
    monkeypatch.setenv("STRIPE_PRICE_PRO", "price_pro")
    checkout = json.dumps({"type": "checkout.session.completed", "data": {"object": {
        "client_reference_id": org["id"], "customer": "cus_1", "subscription": "sub_1", "metadata": {"price_id": "price_team"}}}}).encode()
    bad = client.post("/stripe/webhook", content=checkout, headers={"Stripe-Signature": "t=1,v1=bad"})
    assert bad.status_code == 401
    stale = client.post("/stripe/webhook", content=checkout, headers={"Stripe-Signature": _sig("whsec", checkout, ts="1000")})
    assert stale.status_code == 401
    ok = client.post("/stripe/webhook", content=checkout, headers={"Stripe-Signature": _sig("whsec", checkout)})
    assert ok.status_code == 200 and ok.json()["plan"] == "team"
    assert client.get("/v1/billing", headers=auth(keys["agent"])).json()["plan"] == "team"
    upgrade = json.dumps({"type": "customer.subscription.updated", "data": {"object": {
        "id": "sub_1", "customer": "cus_1", "status": "active", "items": {"data": [{"price": {"id": "price_pro"}}]}}}}).encode()
    assert client.post("/stripe/webhook", content=upgrade, headers={"Stripe-Signature": _sig("whsec", upgrade)}).json()["plan"] == "pro"
    paid = json.dumps({"type": "invoice.paid", "data": {"object": {"id": "in_1", "customer": "cus_1", "amount_paid": 49900,
                                                                     "status_transitions": {"paid_at": 1}}}}).encode()
    client.post("/stripe/webhook", content=paid, headers={"Stripe-Signature": _sig("whsec", paid)})
    assert client.get("/v1/billing", headers=auth(keys["agent"])).json()["stripe"]["last_invoice"]["amount_paid"] == 49900
    gone = json.dumps({"type": "customer.subscription.deleted", "data": {"object": {"id": "sub_1", "customer": "cus_1"}}}).encode()
    assert client.post("/stripe/webhook", content=gone, headers={"Stripe-Signature": _sig("whsec", gone)}).json()["plan"] == "free"
    unknown = json.dumps({"type": "charge.refunded", "data": {"object": {"customer": "cus_zzz"}}}).encode()
    assert "ignored" in client.post("/stripe/webhook", content=unknown, headers={"Stripe-Signature": _sig("whsec", unknown)}).json()
    assert client.post("/v1/billing/checkout", json={"plan": "pro", "success_url": "https://x", "cancel_url": "https://y"},
                       headers=auth(keys["admin"])).status_code == 503  # no STRIPE_SECRET_KEY
