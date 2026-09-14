import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from attest import Attest, PendingStore, SqliteLedger, StoreGate
from attest.cli import main as cli
from attest.descriptor import ActionDescriptor as D
from attest.gate import ConfirmRequest
from attest.gate.slack import APPROVE
from attest.server import AttestServer


def _call(url, method="GET", body=None, headers=None, form=None):
    data = json.dumps(body).encode() if body is not None else (urllib.parse.urlencode(form).encode() if form else None)
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, (json.loads(r.read()) if r.headers.get("Content-Type", "").startswith("application/json") else r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


@pytest.fixture
def stack(tmp_path):
    p = tmp_path / "l.sqlite"
    store, ledger = PendingStore(p), SqliteLedger(p)
    srv = AttestServer(store, ledger, port=0)
    srv.start()
    yield srv, store, ledger, p
    srv.stop()


def test_inbox_page_and_health(stack):
    srv, *_ = stack
    code, page = _call(srv.url + "/")
    assert code == 200 and "Attest — confirm inbox" in page
    assert _call(srv.url + "/healthz")[1] == {"ok": True}
    assert _call(srv.url + "/nope")[0] == 404


def test_pending_confirm_and_ledger_api(stack):
    srv, store, ledger, p = stack
    decided = []
    srv.on_decision = lambda rid, dec: decided.append((rid, dec.status))
    at = Attest(ledger=ledger, gate=StoreGate(store, wait=False), actor="ram@acme.com")

    @at.action(system="gmail", verb="send")
    def send(to, subject):
        return {"id": "m1"}

    from attest import ActionPending
    with pytest.raises(ActionPending) as ei:
        send("x@ext.com", "orig")
    tok = ei.value.resume_token
    code, items = _call(srv.url + "/api/pending")
    assert code == 200 and len(items) == 1 and items[0]["resume_token"] == tok
    rid = items[0]["id"]
    assert _call(srv.url + f"/api/requests/{tok}")[1]["id"] == rid
    code, out = _call(srv.url + f"/confirm/{rid}", "POST", {"status": "approved", "approver": "ram", "edits": {"subject": "E"}})
    assert code == 200 and out["request"]["status"] == "edited" and decided == [(rid, "edited")]
    assert _call(srv.url + f"/confirm/{rid}", "POST", {"status": "rejected"})[0] == 409
    assert _call(srv.url + "/confirm/unknown", "POST", {"status": "approved"})[0] == 404
    assert _call(srv.url + f"/confirm/{rid}", "POST", {"status": "maybe"})[0] == 400  # validation before state
    assert send.resume(tok) == {"id": "m1"}
    code, rows = _call(srv.url + "/api/ledger?limit=5")
    assert code == 200 and rows[0]["confirm"]["status"] == "edited" and rows[0]["seq"] == 2
    assert _call(srv.url + "/api/ledger/verify")[1]["ok"] is True


def test_bad_status_and_bad_json(stack):
    srv, store, *_ = stack
    r = ConfirmRequest("a1", D(system="x", verb="delete"), [], "very_high")
    store.create(r)
    assert _call(srv.url + f"/confirm/{r.id}", "POST", {"status": "maybe"})[0] == 400
    req = urllib.request.Request(srv.url + f"/confirm/{r.id}", data=b"not json", method="POST")
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_token_auth(tmp_path):
    p = tmp_path / "l.sqlite"
    srv = AttestServer(PendingStore(p), SqliteLedger(p), port=0, token="secret")
    srv.start()
    try:
        assert _call(srv.url + "/api/pending")[0] == 401
        assert _call(srv.url + "/api/pending", headers={"Authorization": "Bearer secret"})[0] == 200
        assert _call(srv.url + "/confirm/x", "POST", {"status": "approved"})[0] == 401
        assert "secret" in _call(srv.url + "/")[1]  # the page embeds the token for its own fetches
    finally:
        srv.stop()


def test_slack_interact_endpoint_with_signature(tmp_path):
    p = tmp_path / "l.sqlite"
    store = PendingStore(p)
    srv = AttestServer(store, SqliteLedger(p), port=0, slack_signing_secret="ss")
    srv.start()
    try:
        r = ConfirmRequest("a1", D(system="gmail", verb="send"), [], "high")
        store.create(r)
        payload = {"type": "block_actions", "user": {"id": "U1", "username": "ram"},
                   "actions": [{"action_id": APPROVE, "value": r.id}]}
        body = urllib.parse.urlencode({"payload": json.dumps(payload)}).encode()
        ts = str(int(time.time()))
        sig = "v0=" + hmac.new(b"ss", f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()
        req = urllib.request.Request(srv.url + "/slack/interact", data=body, method="POST",
                                     headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig})
        with urllib.request.urlopen(req, timeout=5) as resp:
            out = json.loads(resp.read())
        assert out["decision"]["status"] == "approved" and store.decision(r.id).approver == "ram (U1)"
        bad = urllib.request.Request(srv.url + "/slack/interact", data=body, method="POST",
                                     headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": "v0=bad"})
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(bad, timeout=5)
        assert ei.value.code == 401
    finally:
        srv.stop()


def test_cli_ledger_pending_confirm_verify_export(tmp_path, capsys):
    p = str(tmp_path / "l.sqlite")
    at = Attest(ledger=SqliteLedger(p), gate=StoreGate(PendingStore(p), wait=False), actor="ram@acme.com")

    @at.action(system="gmail", verb="send")
    def send(to):
        return {"id": "m1"}

    from attest import ActionPending
    with pytest.raises(ActionPending) as ei:
        send("x@ext.com")
    tok = ei.value.resume_token
    assert cli(["--ledger", p, "pending"]) == 0 and tok in capsys.readouterr().out
    assert cli(["--ledger", p, "confirm", tok, "approve", "--edits", '{"to": "y@ext.com"}', "--approver", "cli-ram"]) == 0
    assert "recorded" in capsys.readouterr().out
    assert cli(["--ledger", p, "confirm", tok, "approve"]) == 1
    capsys.readouterr()
    assert send.resume(tok) == {"id": "m1"} and at.ledger.last().params_preview["to"] == "y@ext.com"
    assert cli(["--ledger", p, "ledger"]) == 0 and "gmail.send" in capsys.readouterr().out
    assert cli(["--ledger", p, "ledger", "--json", "--limit", "1"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["seq"] == 2
    assert cli(["--ledger", p, "verify"]) == 0 and "ok=True" in capsys.readouterr().out
    assert cli(["--ledger", p, "export", "--format", "csv"]) == 0 and capsys.readouterr().out.startswith("seq,")
