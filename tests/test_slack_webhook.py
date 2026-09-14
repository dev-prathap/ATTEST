import hashlib
import hmac
import json
import time

from attest import PendingStore
from attest.descriptor import ActionDescriptor as D
from attest.gate import ConfirmRequest
from attest.gate.slack import APPROVE, REJECT, SlackNotifier, blocks_for, handle_interaction, verify_slack_signature
from attest.gate.webhook import WebhookNotifier, verify_signature


class FakeSlack:
    def __init__(self):
        self.posted, self.updated = [], []

    def chat_postMessage(self, **kw):  # noqa: N802
        self.posted.append(kw)
        return {"ok": True, "channel": kw["channel"], "ts": f"{len(self.posted)}.0"}

    def chat_update(self, **kw):  # noqa: N802
        self.updated.append(kw)
        return {"ok": True}


def req():
    return ConfirmRequest("a1", D(system="gmail", verb="send", target="x@ext.com", params={"to": "x@ext.com"}, agent="ag"),
                          ["reaches someone outside"], "high", approvers=["sales"])


def test_notifier_posts_card_and_records_ts():
    store, client = PendingStore(":memory:"), FakeSlack()
    r = req()
    store.create(r)
    SlackNotifier(client, "C1", inbox_url="http://localhost:8321").notify(r, store)
    msg = client.posted[0]
    assert msg["channel"] == "C1" and "gmail.send" in msg["text"]
    actions = [b for b in msg["blocks"] if b["type"] == "actions"][0]["elements"]
    assert [a["action_id"] for a in actions] == [APPROVE, REJECT, "attest_open_inbox"]
    assert actions[0]["value"] == r.id and actions[2]["url"].endswith(f"#{r.id}")
    assert store.get(r.id)["meta"] == {"slack_channel": "C1", "slack_ts": "1.0"}


def test_blocks_mention_reasons_and_hold():
    r = req()
    r.hold = True
    text = json.dumps(blocks_for(r))
    assert "reaches someone outside" in text and "approvers: sales" in text and "needs input fixed" in text


def _payload(action_id, rid, user_id="U1", username="ram"):
    return {"type": "block_actions", "user": {"id": user_id, "username": username},
            "channel": {"id": "C1"}, "message": {"ts": "1.0"},
            "actions": [{"action_id": action_id, "value": rid, "block_id": f"attest:{rid}"}]}


def test_interaction_approve_records_identity_and_updates_card():
    store, client = PendingStore(":memory:"), FakeSlack()
    r = req()
    store.create(r, meta={"slack_channel": "C1", "slack_ts": "1.0"})
    dec = handle_interaction(_payload(APPROVE, r.id), store, client)
    assert dec.status == "approved" and dec.approver == "ram (U1)" and dec.channel == "slack"
    assert store.decision(r.id).status == "approved"
    upd = client.updated[0]
    assert upd["channel"] == "C1" and upd["ts"] == "1.0" and "approved" in upd["text"]


def test_interaction_second_click_does_not_override():
    store, client = PendingStore(":memory:"), FakeSlack()
    r = req()
    store.create(r)
    handle_interaction(_payload(REJECT, r.id, "U2", "bob"), store, client)
    dec = handle_interaction(_payload(APPROVE, r.id), store, client)
    assert dec.status == "rejected" and store.decision(r.id).approver == "bob (U2)"
    assert "already decided" in client.updated[-1]["blocks"][0]["text"]["text"]


def test_interaction_ignores_foreign_payloads():
    store = PendingStore(":memory:")
    assert handle_interaction({"type": "view_submission"}, store) is None
    assert handle_interaction({"type": "block_actions", "actions": [{"action_id": "other"}]}, store) is None


def test_slack_signature():
    secret, body, ts = "s3cr3t", b"payload=%7B%7D", str(int(time.time()))
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()
    assert verify_slack_signature(secret, ts, body, sig)
    assert not verify_slack_signature(secret, ts, body + b"x", sig)
    assert not verify_slack_signature(secret, "12345", body, sig)  # stale
    assert not verify_slack_signature(secret, "abc", body, sig)


def test_webhook_notifier_posts_signed_payload():
    store = PendingStore(":memory:")
    r = req()
    store.create(r)
    sent = {}

    def post(url, body, headers):
        sent.update(url=url, body=body, headers=headers)

    WebhookNotifier("https://example.com/hook", secret="k", confirm_url="http://localhost:8321", post=post).notify(r, store)
    body = json.loads(sent["body"])
    assert sent["url"] == "https://example.com/hook" and body["type"] == "attest.confirm_request"
    assert body["confirm_url"] == f"http://localhost:8321/confirm/{r.id}" and body["params_preview"] == {"to": "x@ext.com"}
    assert "body" not in json.dumps(body)  # no raw content
    ts, sig = sent["headers"]["X-Attest-Timestamp"], sent["headers"]["X-Attest-Signature"]
    assert verify_signature("k", ts, sent["body"], sig) and not verify_signature("wrong", ts, sent["body"], sig)
