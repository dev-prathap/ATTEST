import json
import urllib.request
import uuid

from attest import Attest, AutoGate, SqliteLedger


def _req(method, url, token, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None, method=method,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def test_hubspot_contact_create_and_update_verified(hubspot_token):
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), readers={"hubspot": hubspot_token})
    email = f"attest-live-{uuid.uuid4().hex[:8]}@example.com"

    @at.action(system="hubspot", verb="create", target="contact")
    def create(properties):
        return _req("POST", "https://api.hubapi.com/crm/v3/objects/contacts", hubspot_token, {"properties": properties})

    created = create({"email": email, "firstname": "Attest", "lastname": "Live"})
    assert at.ledger.last().verification.level == "verified", at.ledger.last().verification.evidence

    @at.action(system="hubspot", verb="update", target="contact")
    def update(contact_id, properties):
        return _req("PATCH", f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}", hubspot_token,
                    {"properties": properties})

    update(created["id"], {"lastname": "Updated"})
    v = at.ledger.last().verification
    assert v.level == "verified" and v.evidence["fields"]["lastname"]["ok"], v.evidence
    _req("DELETE", f"https://api.hubapi.com/crm/v3/objects/contacts/{created['id']}", hubspot_token)
