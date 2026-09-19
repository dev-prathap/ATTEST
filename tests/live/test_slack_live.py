import uuid

from tests.live.helpers import api, client

SLACK = "https://slack.com/api/"


def test_slack_post_message_is_verified(slack_token, slack_channel):
    at = client("slack", slack_token)
    text = f"attest live {uuid.uuid4().hex[:8]}"

    @at.action(system="slack", verb="send", target="channel")
    def post(channel, text):
        return api("POST", SLACK + "chat.postMessage", slack_token, {"channel": channel, "text": text})

    post(slack_channel, text)
    v = at.ledger.last().verification
    assert v.level == "verified", v.evidence
    assert v.evidence["fields"]["text"]["ok"] and v.evidence["fields"]["ts"]["ok"]


def test_slack_edited_text_is_unverified(slack_token, slack_channel):
    """Posted one text, the channel holds another — read-back must contradict the claim."""
    at = client("slack", slack_token)
    posted = f"attest live actual {uuid.uuid4().hex[:8]}"

    @at.action(system="slack", verb="send", target="channel")
    def post(channel, text):
        return api("POST", SLACK + "chat.postMessage", slack_token, {"channel": channel, "text": posted})

    post(slack_channel, "what the ledger was told was sent")
    v = at.ledger.last().verification
    assert v.level == "unverified" and "text" in v.evidence["failed"], v.evidence
