"""HTTP gateway against a fake upstream (in-process `send`), plus one real socket round-trip."""
import json
import urllib.error
import urllib.request

import pytest

from attest import Attest, AutoGate, PendingStore, SqliteLedger, StoreGate
from attest.gate import ConfirmDecision
from attest.gateway.server import Gateway, Upstream
from attest.policy import PolicyEngine


class FakeCRM:
    """Upstream that stores leads; `lose=True` acknowledges updates without persisting (a contradiction)."""

    def __init__(self):
        self.leads, self.calls, self.lose = {}, [], False

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        path = url.split("//", 1)[-1].split("/", 1)[-1]
        if headers.get("Authorization") != "Bearer tok":
            return 401, {"Content-Type": "application/json"}, b'{"error":"unauthorized"}'
        if method == "POST" and path == "v2/leads":
            lead = {"id": f"L-{len(self.leads) + 1}", **json.loads(body)}
            self.leads[lead["id"]] = lead
            return 201, {"Content-Type": "application/json"}, json.dumps(lead).encode()
        if method == "PATCH" and path.startswith("v2/leads/"):
            lid = path.rsplit("/", 1)[-1]
            if lid not in self.leads:
                return 404, {"Content-Type": "application/json"}, b'{"error":"not found"}'
            if not self.lose:
                self.leads[lid].update(json.loads(body))
            return 200, {"Content-Type": "application/json"}, b'{"ok":true}'
        if method == "GET" and path.startswith("v2/leads/"):
            lid = path.rsplit("/", 1)[-1]
            if lid in self.leads:
                return 200, {"Content-Type": "application/json"}, json.dumps(self.leads[lid]).encode()
            return 404, {"Content-Type": "application/json"}, b'{"error":"not found"}'
        if method == "GET" and path == "v2/leads":
            return 200, {"Content-Type": "application/json"}, json.dumps(list(self.leads.values())).encode()
        if method == "DELETE":
            self.leads.pop(path.rsplit("/", 1)[-1], None)
            return 204, {}, b""
        return 500, {}, b"boom"


@pytest.fixture
def crm():
    return FakeCRM()


def gateway(crm, gate=None, **kw):
    at = Attest(ledger=SqliteLedger(":memory:"), gate=gate or AutoGate(approver="tester"), actor="ram@acme.com", agent="gw-agent")
    return Gateway(at, upstream=Upstream(send=crm), **kw), at


H = {"Authorization": "Bearer tok", "Content-Type": "application/json"}


def test_create_forwarded_verified_by_convention(crm):
    gw, at = gateway(crm)
    status, headers, raw = gw.handle("POST", "/https://api.someweirdcrm.io/v2/leads", H, b'{"name": "Arun", "email": "arun@newco.com"}')
    assert status == 201 and json.loads(raw)["id"] == "L-1"
    assert headers["X-Attest-Level"] == "verified" and headers["X-Attest-Decision"] == "ask" and headers["X-Attest-Seq"] == "1"
    e = at.ledger.last()
    assert (e.descriptor["system"], e.descriptor["verb"], e.descriptor["target"]) == ("someweirdcrm", "create", "leads")
    assert e.confirm.status == "approved" and e.verification.method == "read-back:convention"
    assert set(e.verification.evidence["fields"]) == {"id", "name", "email"}
    # the read-back GET reused the caller's Authorization header
    reads = [c for c in crm.calls if c[0] == "GET"]
    assert reads and reads[0][2]["Authorization"] == "Bearer tok"


def test_lost_update_is_unverified_and_auth_forwarded(crm):
    gw, at = gateway(crm)
    gw.handle("POST", "/https://api.someweirdcrm.io/v2/leads", H, b'{"name": "A"}')
    crm.lose = True
    status, headers, _ = gw.handle("PATCH", "/https://api.someweirdcrm.io/v2/leads/L-1", H, b'{"name": "B"}')
    assert status == 200 and headers["X-Attest-Level"] == "unverified"
    assert at.ledger.last().verification.evidence["failed"] == ["name"]


def test_relative_path_with_upstream_header_and_reads_pass_through(crm):
    gw, at = gateway(crm)
    status, _, raw = gw.handle("GET", "/v2/leads", {**H, "X-Attest-Upstream": "https://api.someweirdcrm.io"}, b"")
    assert status == 200 and json.loads(raw) == [] and at.ledger.count() == 0  # reads not recorded by default
    status, _, raw = gw.handle("GET", "/v2/leads", H, b"")
    assert status == 400 and "no upstream" in raw.decode()
    gw2, at2 = gateway(crm, record_reads=True)
    gw2.handle("GET", "/https://api.someweirdcrm.io/v2/leads", H, b"")
    assert at2.ledger.last().descriptor["verb"] == "list"


def test_refuse_and_reject_never_reach_upstream(crm):
    gw, at = gateway(crm, gate=AutoGate("rejected", approver="bob"))
    status, _, raw = gw.handle("DELETE", "/https://api.someweirdcrm.io/v2/leads/L-1", H, b"")
    assert status == 403 and "rejected" in raw.decode() and not any(c[0] == "DELETE" for c in crm.calls)
    gw.at.policy = PolicyEngine.from_yaml("policies:\n  - match: {verb: create}\n    decision: refuse\n")
    status, _, raw = gw.handle("POST", "/https://api.someweirdcrm.io/v2/leads", H, b'{"name": "x"}')
    assert status == 403 and json.loads(raw)["error"] == "attest refused" and not any(c[0] == "POST" for c in crm.calls)
    assert [e.decision for e in at.ledger.entries()] == ["ask", "refuse"]


def test_edits_at_confirm_change_the_forwarded_body(crm):
    gw, at = gateway(crm, gate=AutoGate("approved", edits={"name": "EDITED"}))
    status, _, raw = gw.handle("POST", "/https://api.someweirdcrm.io/v2/leads", H, b'{"name": "orig", "email": "a@b.com"}')
    assert status == 201 and json.loads(raw)["name"] == "EDITED" and crm.leads["L-1"]["email"] == "a@b.com"
    assert at.ledger.last().confirm.status == "edited"


def test_upstream_error_is_recorded_as_failed(crm):
    gw, at = gateway(crm)
    status, headers, raw = gw.handle("POST", "/https://api.someweirdcrm.io/v2/leads", {"Authorization": "Bearer WRONG", "Content-Type": "application/json"}, b'{"name": "x"}')
    assert status == 401 and "X-Attest-Level" in headers
    e = at.ledger.last()
    assert e.execution.status == "failed" and "401" in e.execution.error


def test_pending_mode_then_resume(crm):
    store = PendingStore(":memory:")
    gw, at = gateway(crm, gate=StoreGate(store, wait=False))
    status, _, raw = gw.handle("POST", "/https://api.someweirdcrm.io/v2/leads", H, b'{"name": "Later"}')
    out = json.loads(raw)
    assert status == 202 and out["status"] == "pending_confirmation" and not crm.leads
    tok = out["resume_token"]
    assert gw.handle("POST", f"/_attest/resume/{tok}", {}, b"")[0] == 202
    store.decide(tok, ConfirmDecision("edited", "ram", {"name": "Approved"}))
    status, headers, raw = gw.handle("POST", f"/_attest/resume/{tok}", {}, b"")
    assert status == 201 and json.loads(raw)["name"] == "Approved" and headers["X-Attest-Level"] == "verified"
    assert at.ledger.last().confirm.approver == "ram" and at.ledger.last().resumed_from
    assert gw.handle("POST", "/_attest/resume/nope", {}, b"")[0] == 404
    ok, _, raw = gw.handle("GET", "/_attest/ledger", {}, b"")
    assert ok == 200 and json.loads(raw)[0]["level"] == "verified"
    assert json.loads(gw.handle("GET", "/_attest/healthz", {}, b"")[2])["ok"]


def test_form_bodies_and_query_params(crm):
    gw, at = gateway(crm)
    gw.handle("POST", "/https://api.someweirdcrm.io/v2/leads?source=web", {"Authorization": "Bearer tok", "Content-Type": "application/x-www-form-urlencoded"}, b"name=Form+Lead")
    p = at.ledger.last().params_preview
    assert p["name"] == "Form Lead" and at.ledger.last().params_hash


def test_known_host_gets_recipe_reader(crm):
    gw, at = gateway(crm)
    readers = gw._readers("https://api.hubapi.com/crm/v3/objects/deals", {"authorization": "Bearer hs-token"})
    assert readers == {"hubspot": "hs-token"}
    assert gw._readers("https://api.someweirdcrm.io/v2/leads", {"authorization": "Bearer tok"}) is None
    assert gw._readers("https://api.linear.app/graphql", {"authorization": "lin_api_x"}) == {"linear": "lin_api_x"}


def test_real_socket_roundtrip(crm):
    gw, at = gateway(crm)
    base = gw.start(port=0)
    try:
        req = urllib.request.Request(f"{base}/https://api.someweirdcrm.io/v2/leads", data=b'{"name": "Sock"}', method="POST", headers=H)
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 201 and r.headers["X-Attest-Level"] == "verified" and json.loads(r.read())["name"] == "Sock"
        with urllib.request.urlopen(f"{base}/_attest/healthz", timeout=5) as r:
            assert json.loads(r.read())["ok"]
        req = urllib.request.Request(f"{base}/v2/leads", headers={"Authorization": "Bearer tok"})
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=5)
        assert ei.value.code == 400
    finally:
        gw.stop()


def test_cli_entry_points_exist():
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-m", "attest.cli", "gateway", "--help"], capture_output=True, text=True)
    assert "attest-gateway" in out.stdout or "outbound" in out.stdout


def test_openapi_driver_is_wired(crm):
    from attest.verify.drivers.openapi import OpenApiDriver
    spec = {"servers": [{"url": "https://api.someweirdcrm.io/v2"}], "paths": {"/leads": {"post": {}}, "/leads/{leadId}": {"get": {}}}}
    gw, at = gateway(crm)
    drv = OpenApiDriver(spec, http_get=lambda url, params=None: json.loads(crm("GET", url, {"Authorization": "Bearer tok"}, None)[2]))
    gw2 = Gateway(at, upstream=Upstream(send=crm), openapi=drv)
    assert at.drivers[0] is drv
    _, headers, _ = gw2.handle("POST", "/https://api.someweirdcrm.io/v2/leads", H, b'{"name": "Spec"}')
    assert headers["X-Attest-Level"] == "verified" and at.ledger.last().verification.method == "read-back:openapi"
