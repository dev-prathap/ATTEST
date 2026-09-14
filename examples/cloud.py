"""SDK ⇄ Attest Cloud. Start the cloud (deploy/docker-compose.yml or `uvicorn attest_cloud.main:app --port 8400`),
bootstrap an org, then:  ATTEST_CLOUD_URL=http://127.0.0.1:8400 ATTEST_API_KEY=atk_… python examples/cloud.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from attest import Attest  # noqa: E402

at = Attest.cloud(wait=False, agent="cloud-demo@v1", actor="ram@acme.com", ledger_path=":memory:")
print("org:", at.cloud_client.me()["org"]["name"], "policy v", getattr(at.policy, "cloud_version", "?"))


@at.action(system="hubspot", verb="update", target="deal_id")
def update_deal(deal_id, dealstage):
    return {"id": deal_id, "properties": {"dealstage": dealstage}}


update_deal("777", "proposal_sent")                       # act ⇒ pushed to the cloud ledger
print("cloud ledger head:", at.cloud_client.ledger(limit=1)[0]["hash"][:12], "outbox:", at.ledger.pending_count())


@at.action(system="gmail", verb="send", target="to")
def send_email(to, subject):
    return {"id": "m1"}


try:
    send_email("arun@newco.com", "Proposal")                # ask ⇒ pending in the cloud inbox
except Exception as e:  # ActionPending
    print("pending:", e)
    print("approve it in the dashboard, then: send_email.resume(<token>)")
