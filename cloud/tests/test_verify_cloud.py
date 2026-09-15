"""P3.3: server-side read-back through Nango connections, and the SDK's CloudVerifyDriver."""
import json

from attest_cloud.main import app
from conftest import auth

from attest import Attest
from attest.cloud import CloudClient, CloudVerifyDriver


class FakeNango:
    """`fetch(provider_config_key, connection_id)` → Nango connection payload."""

    def __init__(self):
        self.calls = []

    def __call__(self, key, cid):
        self.calls.append((key, cid))
        if cid == "missing":
            from attest.verify.readers import ReadBackError
            raise ReadBackError("nango: HTTP 404")
        return {"credentials": {"access_token": f"tok-{key}"}}


def _configure(client, keys):
    client.put("/v1/settings", json={"nango_url": "http://nango", "nango_secret": "s3",
                                     "nango_connections": {"gmail": {"provider_config_key": "google-mail", "connection_id": "c1"},
                                                           "slack": {"provider_config_key": "slack", "connection_id": "missing"}}},
               headers=auth(keys["admin"])).raise_for_status()
    st = client.get("/v1/settings", headers=auth(keys["admin"])).json()
    assert st["nango_secret"] == "s3…"[:3] + "…" or st["nango_secret"].endswith("…")


def test_verify_endpoint_reads_back_with_nango_token(client, keys, monkeypatch):
    _configure(client, keys)
    nango = FakeNango()
    app.state.nango_fetch = nango
    seen = {}

    def fake_http_get(url, params=None, *, token=None, headers=None, timeout=20.0):
        seen["url"], seen["token"] = url, token
        return {"id": "m1", "labelIds": ["SENT"], "payload": {"headers": [{"name": "To", "value": "arun@newco.com"}, {"name": "Subject", "value": "Hi"}]}}
    monkeypatch.setattr("attest.verify.readers.http_get", fake_http_get)
    body = {"descriptor": {"system": "gmail", "verb": "send", "target": "arun@newco.com", "params": {"to": "arun@newco.com", "subject": "Hi"}},
            "result": {"id": "m1"}}
    out = client.post("/v1/verify", json=body, headers=auth(keys["agent"])).json()
    assert out["level"] == "verified" and out["read_back_available"] and out["evidence"]["fields"]["subject"]["ok"]
    assert seen["token"] == "tok-google-mail" and "messages/m1" in seen["url"]
    assert ("google-mail", "c1") in nango.calls and ("slack", "missing") in nango.calls  # missing one is skipped
    body["descriptor"]["params"]["to"] = "else@x.com"
    assert client.post("/v1/verify", json=body, headers=auth(keys["agent"])).json()["level"] == "unverified"
    out = client.post("/v1/verify", json={**body, "record": True}, headers=auth(keys["agent"])).json()
    assert out["seq"] == 1 and client.get("/v1/ledger", headers=auth(keys["agent"])).json()[0]["verification"]["level"] == "unverified"
    out = client.post("/v1/verify", json={"descriptor": {"system": "slack", "verb": "send"}, "result": {"ts": "1"}}, headers=auth(keys["agent"])).json()
    assert out["level"] == "acknowledged" and not out["read_back_available"] and "no read-back" in out["evidence"]["detail"]
    del app.state.nango_fetch


def test_verify_without_nango_is_plain_ladder(client, keys):
    out = client.post("/v1/verify", json={"descriptor": {"system": "gmail", "verb": "send"}, "result": {"id": "m1"}}, headers=auth(keys["agent"])).json()
    assert out["level"] == "acknowledged" and not out["read_back_available"]


def test_sdk_cloud_verify_driver(client, keys, monkeypatch):
    _configure(client, keys)
    app.state.nango_fetch = FakeNango()
    monkeypatch.setattr("attest.verify.readers.http_get", lambda url, params=None, **kw: {
        "id": "m1", "labelIds": ["SENT"], "payload": {"headers": [{"name": "To", "value": "arun@newco.com"}]}})

    def transport(method, url, body, headers):
        path = url.split("//", 1)[-1].split("/", 1)[1]
        r = client.request(method, "/" + path, content=body, headers=headers)
        try:
            return r.status_code, r.json()
        except json.JSONDecodeError:
            return r.status_code, r.text
    at = Attest.cloud("http://cloud", keys["agent"], transport=transport, ledger_path=":memory:", cloud_verify=True, actor="ram@acme.com")
    from attest import AutoGate
    at.gate = AutoGate()
    assert isinstance(at.cloud_verify, CloudVerifyDriver)

    @at.action(system="gmail", verb="send", target="to")
    def send(to):
        return {"id": "m1"}

    send("arun@newco.com")
    v = at.ledger.last().verification
    assert v.level == "verified" and v.method == "read-back:cloud" and v.evidence["via"] == "cloud"
    send("else@x.com")
    assert at.ledger.last().verification.level == "unverified"

    @at.action(system="slack", verb="send")
    def post(channel):
        return {"ts": "1"}

    post("C1")
    assert at.ledger.last().verification.level == "acknowledged"  # cloud has no slack connection ⇒ degrade
    only = Attest.cloud("http://cloud", keys["agent"], transport=transport, ledger_path=":memory:", cloud_verify={"hubspot"})
    assert not only.cloud_verify.supports(__import__("attest.descriptor", fromlist=["ActionDescriptor"]).ActionDescriptor(system="gmail", verb="send"))
    del app.state.nango_fetch
    _ = CloudClient
