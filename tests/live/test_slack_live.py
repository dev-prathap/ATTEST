import json
import urllib.request
import uuid

from attest import Attest, AutoGate, SqliteLedger


def _api(method, token, body):
    req = urllib.request.Request(f"https://slack.com/api/{method}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def test_slack_post_message_is_verified(slack_token, slack_channel):
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), readers={"slack": slack_token})
    text = f"attest live {uuid.uuid4().hex[:8]}"

    @at.action(system="slack", verb="send", target="channel")
    def post(channel, text):
        return _api("chat.postMessage", slack_token, {"channel": channel, "text": text})

    post(slack_channel, text)
    v = at.ledger.last().verification
    assert v.level == "verified", v.evidence
    assert v.evidence["fields"]["text"]["ok"] and v.evidence["fields"]["ts"]["ok"]
