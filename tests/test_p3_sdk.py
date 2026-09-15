"""P3.4 recipe automation, P3.5 anchoring + Ed25519, P3.6 Teams / email / links / digest."""
import json
import subprocess
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import pytest

from attest import Attest, AutoGate, PendingStore, SqliteLedger, StoreGate
from attest.cli import main as cli
from attest.descriptor import ActionDescriptor as D
from attest.digest import anomalies, digest, render_text, slack_blocks
from attest.gate import ConfirmRequest
from attest.gate.email import EmailNotifier
from attest.gate.links import decision_links, verify_link
from attest.gate.teams import TeamsNotifier
from attest.ledger import LedgerEntry, signing
from attest.ledger import anchor as an
from attest.ledger.checkpoints import Checkpoint
from attest.server import AttestServer
from attest.verify import recipes
from attest.verify.readers import ReadBackError
from attest.verify.recipes import generate
from attest.verify.recipes.declarative import load_dir, make_recipe

# ── P3.4 declarative recipes + proposals ──────────────────────────────────────
SPEC = {"name": "xcrm.lead", "system": "xcrm", "verbs": ["create", "update"], "target": "lead",
        "read": {"method": "GET", "url": "https://api.x.io/v2/leads/{id}", "id": "$.id|$params.lead_id"},
        "compare": {"fields": ["name", "stage"], "checks": [{"path": "status", "equals": "active"}]}, "source": "community"}
DB = {"L-1": {"id": "L-1", "name": "Arun", "stage": "new", "status": "active", "secret": "x"}}


def http_get(url, params=None):
    key = url.rsplit("/", 1)[-1]
    if key not in DB:
        raise ReadBackError("HTTP 404")
    return DB[key]


def test_declarative_recipe_verifies_and_contradicts():
    r = make_recipe(SPEC)
    assert r.matches(D(system="xcrm", verb="create", target="lead"), {}) and not r.matches(D(system="xcrm", verb="delete"), {})
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), readers={"xcrm": http_get}, drivers=[])
    recipes.register(r)
    try:
        @at.action(system="xcrm", verb="create", target="lead")
        def create(name, stage, secret):
            return {"id": "L-1"}

        create("Arun", "new", "x")
        v = at.ledger.last().verification
        assert v.level == "verified" and set(v.evidence["fields"]) == {"name", "stage", "status"} and "secret" not in v.evidence["fields"]

        @at.action(system="xcrm", verb="update", target="lead")
        def update(lead_id, stage):
            return {"ok": True}

        update("L-1", "won")
        assert at.ledger.last().verification.level == "unverified"
        DB["L-1"]["status"] = "archived"
        update("L-1", "new")
        assert "status" in at.ledger.last().verification.evidence["failed"]
    finally:
        recipes._REGISTRY["xcrm"].remove(r)
        DB["L-1"]["status"] = "active"


def test_load_dir_and_registry_example(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps([SPEC, {"name": "bad"}]))
    (tmp_path / "junk.json").write_text("not json")
    loaded = load_dir(tmp_path)
    assert [r.name for r in loaded] == ["xcrm.lead"]
    recipes._REGISTRY["xcrm"].remove(loaded[0])
    assert any(r.name == "someweirdcrm.lead" and r.source == "community" for r in recipes.all_recipes())


OPENAPI = {"servers": [{"url": "https://api.x.io/v2"}], "paths": {
    "/leads": {"post": {"requestBody": {"content": {"application/json": {"schema": {"properties": {"name": {}, "email": {}, "secret": {}}}}}}}},
    "/leads/{leadId}": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {"properties": {"id": {}, "name": {}, "email": {}}}}}}}}, "patch": {}},
    "/emails/send": {"post": {}}}}


def test_propose_from_openapi_and_mcp_and_llm_refine():
    props = generate.from_openapi(OPENAPI, "xcrm")
    assert [p["name"] for p in props] == ["xcrm.lead.create", "xcrm.lead.update"]
    assert props[0]["read"]["url"] == "https://api.x.io/v2/leads/{id}" and props[0]["compare"]["fields"] == ["email", "name"]
    assert props[1]["read"]["id"] == "$params.leadId|$.id"
    tools = [{"name": "create_issue", "inputSchema": {"properties": {"title": {}, "team": {}}}},
             {"name": "get_issue", "inputSchema": {"properties": {"issue_id": {}}, "required": ["issue_id"]}},
             {"name": "update_issue", "inputSchema": {"properties": {"issue_id": {}, "title": {}}, "required": ["issue_id"]}},
             {"name": "delete_issue", "inputSchema": {"properties": {"issue_id": {}}, "required": ["issue_id"]}}]
    mp = generate.from_mcp_tools(tools, "tracker")
    assert [p["name"] for p in mp] == ["tracker.issue.create", "tracker.issue.update"]
    assert mp[0]["read"] == {"mcp_tool": "get_issue", "id_arg": "issue_id", "id": "$.id"} and mp[0]["compare"]["fields"] == ["team", "title"]
    refined = generate.refine_with_llm(props, call=lambda prompt: 'sure: [{"name": "xcrm.lead.create", "compare": {"fields": ["name"], "checks": [{"path": "status", "equals": "active"}]}}]')
    assert refined[0]["compare"]["fields"] == ["name"] and refined[0]["compare"]["checks"][0]["path"] == "status" and refined[0]["source"] == "openapi+llm"
    assert refined[1]["source"] == "openapi"
    assert generate.refine_with_llm(props, call=lambda p: "no json here") == props


def test_cli_recipes(tmp_path, capsys, monkeypatch):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(OPENAPI))
    assert cli(["recipes", "propose", "--openapi", str(spec), "--system", "xcrm", "--out", str(tmp_path / "props")]) == 0
    out = capsys.readouterr().out
    assert "2 proposal(s)" in out
    assert cli(["recipes", "install", str(tmp_path / "props" / "xcrm.json"), "--dir", str(tmp_path / "installed")]) == 0
    installed = json.loads((tmp_path / "installed" / "xcrm.json").read_text())
    assert installed[0]["source"] == "reviewed"
    assert cli(["recipes", "list"]) == 0 and "gmail.send" in capsys.readouterr().out
    assert cli(["recipes", "propose", "--system", "x"]) == 2


# ── P3.5 anchoring + Ed25519 ──────────────────────────────────────────────────
def test_file_and_http_anchor(tmp_path):
    L = SqliteLedger(":memory:", signing_key="k")
    for _ in range(3):
        L.append(LedgerEntry.from_descriptor(D(system="x", verb="get"), decision="act", risk_tier="low"))
    cp = L.checkpoint()
    fa = an.FileAnchor(tmp_path / "anchors.jsonl")
    r = fa.publish(cp)
    assert r.ref == "line:1" and an.verify_anchor(fa, cp)
    assert not an.verify_anchor(fa, Checkpoint(3, "f" * 64, cp.signed_at))
    posted = {}
    ha = an.HttpAnchor("https://anchor.example/v1", api_key="k", post=lambda url, body, h: posted.update(url=url, body=json.loads(body), h=h) or {"id": "rcpt-1"},
                       get=lambda url, h: {"id": "rcpt-1", "anchored_at": "t"} if cp.hash in url else None)
    r = ha.publish(cp)
    assert r.ref == "rcpt-1" and posted["h"]["Authorization"] == "Bearer k" and posted["body"]["hash"] == cp.hash
    assert an.verify_anchor(ha, cp) and not an.verify_anchor(ha, Checkpoint(9, "0" * 64, cp.signed_at))


def test_git_anchor(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    cp = Checkpoint(4, "a" * 64, "2026-01-01T00:00:00+00:00", "org:acme")
    ga = an.GitAnchor(tmp_path)
    r = ga.publish(cp)
    assert len(r.ref) == 40 and an.verify_anchor(ga, cp) and not an.verify_anchor(ga, Checkpoint(4, "b" * 64, cp.signed_at, "org:acme"))


def test_cli_anchor(tmp_path, capsys):
    p = str(tmp_path / "l.sqlite")
    L = SqliteLedger(p)
    L.append(LedgerEntry.from_descriptor(D(system="x", verb="get"), decision="act", risk_tier="low"))
    assert cli(["--ledger", p, "anchor", "--file", str(tmp_path / "a.jsonl")]) == 1  # no checkpoint yet
    cli(["--ledger", p, "checkpoint"])
    capsys.readouterr()
    assert cli(["--ledger", p, "anchor", "--file", str(tmp_path / "a.jsonl")]) == 0
    assert json.loads(capsys.readouterr().out)["ref"] == "line:1"
    assert cli(["--ledger", p, "anchor", "--file", str(tmp_path / "a.jsonl"), "--verify"]) == 0
    assert cli(["--ledger", p, "anchor"]) == 2


@pytest.mark.skipif(not signing.available(), reason="cryptography not installed")
def test_ed25519_checkpoint_signing():
    priv, pub = signing.generate_keypair()
    cp = signing.sign_checkpoint(Checkpoint(1, "c" * 64, "2026-01-01T00:00:00+00:00"), priv)
    assert cp.signature.startswith("ed25519=") and cp.key_id == "ed25519"
    assert signing.verify_checkpoint(cp, pub) and not signing.verify_checkpoint(cp, signing.generate_keypair()[1])
    assert not signing.verify(b"m", "v1=abc", pub)


# ── P3.6 Teams / email / links / digest ───────────────────────────────────────
def req():
    return ConfirmRequest("a1", D(system="gmail", verb="send", target="x@ext.com", params={"to": "x@ext.com"}, agent="ag"),
                          ["external"], "high", approver_members=["priya@acme.com"])


def test_links_roundtrip_and_expiry():
    approve, reject = decision_links("http://inbox", "cfm_1", "s", ttl_s=60)
    assert "/decide/cfm_1/approved?" in approve and "/decide/cfm_1/rejected?" in reject
    q = dict(x.split("=") for x in approve.split("?")[1].split("&"))
    assert verify_link("s", "cfm_1", "approved", int(q["exp"]), q["sig"]) and not verify_link("s", "cfm_1", "rejected", int(q["exp"]), q["sig"])
    assert not verify_link("s", "cfm_1", "approved", 1, q["sig"])


def test_teams_card_and_email_message():
    store = PendingStore(":memory:")
    r = req()
    store.create(r)
    posted = {}
    TeamsNotifier("https://teams.webhook", inbox_url="http://inbox", link_secret="s", post=lambda url, body: posted.update(url=url, body=json.loads(body))).notify(r, store)
    card = posted["body"]["attachments"][0]["content"]
    assert [a["title"] for a in card["actions"]] == ["Approve", "Reject", "Open inbox"] and "/decide/" in card["actions"][0]["url"]
    assert store.get(r.id)["meta"]["teams_webhook"]
    sent = []
    EmailNotifier("fallback@acme.com", sender="attest@acme.com", inbox_url="http://inbox", link_secret="s", send=sent.append).notify(r, store)
    msg: EmailMessage = sent[0]
    assert msg["To"] == "priya@acme.com" and "[Attest] Confirm gmail.send" in msg["Subject"] and "Approve: http://inbox/decide/" in msg.get_body(("plain",)).get_content()
    assert store.get(r.id)["meta"]["email_to"] == ["priya@acme.com"]


def test_server_one_click_links(tmp_path):
    import urllib.request
    p = tmp_path / "l.sqlite"
    store = PendingStore(p)
    srv = AttestServer(store, SqliteLedger(p), port=0, link_secret="s")
    srv.start()
    try:
        r = req()
        store.create(r)
        approve, _ = decision_links(srv.url, r.id, "s")
        with urllib.request.urlopen(approve, timeout=5) as resp:
            assert "Approved" in resp.read().decode()
        assert store.decision(r.id).status == "approved" and store.decision(r.id).approver == "one-click-link"
        with urllib.request.urlopen(approve, timeout=5) as resp:
            assert "Already decided" in resp.read().decode()
        bad = approve.replace("sig=", "sig=0")
        with urllib.request.urlopen(bad, timeout=5) as resp:
            assert "invalid" in resp.read().decode()
    finally:
        srv.stop()


def _entries(spec):
    """spec: list of (agent, system, verb, level, target_class, hours_ago)."""
    out = []
    for i, (agent, system, verb, level, tc, hours) in enumerate(spec):
        d = D(system=system, verb=verb, target="x@ext.com" if tc == "external" else None, agent=agent)
        e = LedgerEntry.from_descriptor(d, decision="act", risk_tier="high", target_class=tc)
        e.verification.level = level
        e.created_at = datetime.now(UTC) - timedelta(hours=hours)
        e.seq = i + 1
        out.append(e)
    return out


def test_digest_summary_and_anomalies():
    base = [("bot", "gmail", "send", "verified", "internal", 24 * d + 12) for d in range(1, 8)]
    window = [("bot", "gmail", "send", "verified", "internal", 1)] + [("bot", "gmail", "send", "unverified", "external", 2)] * 4 \
        + [("newbot", "stripe", "pay", "acknowledged", "none", 3)] + [("bot", "hubspot", "update", "acknowledged", "none", 0.5)] * 12
    entries = _entries(base + window)
    d = digest(entries, since_hours=24)
    s = d["summary"]
    assert s["actions"] == 18 and s["by_level"]["unverified"] == 4 and len(s["unverified"]) == 4 and d["baseline"]["actions"] == 7
    flags = {a["flag"] for a in d["anomalies"]}
    assert {"new_action", "volume_spike", "unverified_spike"} <= flags
    text = render_text(d)
    assert "UNVERIFIED (4)" in text and "volume_spike" in text and slack_blocks(d)[0]["type"] == "header"
    assert anomalies([], []) == [] and digest([], since_hours=1)["summary"]["actions"] == 0


def test_cli_digest(tmp_path, capsys):
    p = str(tmp_path / "l.sqlite")
    at = Attest(ledger=SqliteLedger(p), gate=AutoGate(), agent="cli-bot")
    at.action(system="x", verb="get")(lambda i: i)(1)
    assert cli(["--ledger", p, "digest", "--since", "1"]) == 0 and "1 actions" in capsys.readouterr().out
    assert cli(["--ledger", p, "digest", "--json"]) == 0 and json.loads(capsys.readouterr().out)["summary"]["by_agent"] == {"cli-bot": 1}


def test_store_gate_with_teams_and_email_notifiers():
    store = PendingStore(":memory:")
    posted, sent = [], []
    gate = StoreGate(store, wait=False, notifiers=[
        TeamsNotifier("https://t", inbox_url="http://i", link_secret="s", post=lambda u, b: posted.append(b)),
        EmailNotifier("ops@acme.com", sender="a@b", inbox_url="http://i", link_secret="s", send=sent.append)])
    at = Attest(ledger=SqliteLedger(":memory:"), gate=gate)
    from attest import ActionPending
    with pytest.raises(ActionPending):
        at.action(system="gmail", verb="send")(lambda to: 1)("x@ext.com")
    assert len(posted) == 1 and len(sent) == 1 and gate.name == "teams+email"
