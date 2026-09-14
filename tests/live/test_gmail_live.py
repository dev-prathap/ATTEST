import base64
import json
import os
import urllib.request
import uuid

from attest import Attest, AutoGate, SqliteLedger


def _post(url, token, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def test_gmail_send_is_verified_by_read_back(gmail_token):
    to = os.environ.get("ATTEST_LIVE_GMAIL_TO") or "me"
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), readers={"gmail": gmail_token}, actor="live@test")
    subject = f"attest live {uuid.uuid4().hex[:8]}"

    @at.action(system="gmail", verb="send", target="to")
    def send(to, subject, body):
        raw = base64.urlsafe_b64encode(f"To: {to}\r\nSubject: {subject}\r\n\r\n{body}".encode()).decode()
        return _post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", gmail_token, {"raw": raw})

    send(to, subject, "sent by the attest live test")
    v = at.ledger.last().verification
    assert v.level == "verified", v.evidence
    assert v.evidence["checks"]["label:SENT"] and v.evidence["fields"]["subject"]["ok"]
