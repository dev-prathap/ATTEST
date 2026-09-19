import uuid

from tests.live.helpers import api, client

CRM = "https://api.hubapi.com/crm/v3/objects/contacts"


def test_hubspot_contact_create_update_and_contradiction(hubspot_token):
    at = client("hubspot", hubspot_token)
    email = f"attest-live-{uuid.uuid4().hex[:8]}@example.com"

    @at.action(system="hubspot", verb="create", target="contact")
    def create(properties):
        return api("POST", CRM, hubspot_token, {"properties": properties})

    created = create({"email": email, "firstname": "Attest", "lastname": "Live"})
    assert at.ledger.last().verification.level == "verified", at.ledger.last().verification.evidence

    @at.action(system="hubspot", verb="update", target="contact")
    def update(contact_id, properties):
        return api("PATCH", f"{CRM}/{contact_id}", hubspot_token, {"properties": properties})

    update(created["id"], {"lastname": "Updated"})
    v = at.ledger.last().verification
    assert v.level == "verified" and v.evidence["fields"]["lastname"]["ok"], v.evidence

    @at.action(system="hubspot", verb="update", target="contact")
    def update_lost(contact_id, properties):
        return {"id": contact_id}                 # the vendor "accepted" it; nothing was written

    update_lost(created["id"], {"lastname": "NeverWritten"})
    v = at.ledger.last().verification
    assert v.level == "unverified" and "lastname" in v.evidence["failed"], v.evidence
    api("DELETE", f"{CRM}/{created['id']}", hubspot_token)
