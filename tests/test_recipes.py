"""Recipe behaviour against fakes shaped like the real clients. Live tests live in tests/live/."""
import pytest

from attest import Attest, AutoGate, SqliteLedger
from attest.descriptor import ActionDescriptor as D
from attest.verify import recipes
from attest.verify.drivers.recipe import RecipeDriver
from attest.verify.ladder import verify


# ── Gmail ─────────────────────────────────────────────────────────────────────
class FakeGmail:
    def __init__(self):
        self.msgs, self.drafts_ = {}, {}

    def users(self):
        return self

    def messages(self):
        return _Res(self.msgs)

    def drafts(self):
        return _Res(self.drafts_)


class _Res:
    def __init__(self, store):
        self.store = store

    def get(self, userId, id, format=None, metadataHeaders=None):
        data = self.store.get(id)
        if data is None:
            raise Exception("HttpError 404")
        return type("R", (), {"execute": lambda s: data})()


def gmail_msg(mid, to, subject, labels=("SENT",), thread="t1", cc=""):
    return {"id": mid, "threadId": thread, "labelIds": list(labels),
            "payload": {"headers": [{"name": "To", "value": to}, {"name": "Cc", "value": cc}, {"name": "Subject", "value": subject}]}}


@pytest.fixture
def gmail():
    return FakeGmail()


@pytest.fixture
def at(gmail):
    return Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), actor="ram@acme.com", readers={"gmail": gmail})


def test_gmail_send_verified(at, gmail):
    @at.action(system="gmail", verb="send", target="to")
    def send(to, subject, body):
        gmail.msgs["m1"] = gmail_msg("m1", f"Arun <{to}>", subject)
        return {"id": "m1", "threadId": "t1"}
    send("arun@newco.com", "Hello", "…")
    v = at.ledger.last().verification
    assert v.level == "verified" and v.method == "read-back:recipe" and v.matched is True
    assert v.evidence["checks"]["label:SENT"] and v.evidence["fields"]["subject"]["ok"]


def test_gmail_send_not_in_sent_is_unverified(at, gmail):
    @at.action(system="gmail", verb="send", target="to")
    def send(to, subject, body):
        gmail.msgs["m1"] = gmail_msg("m1", to, subject, labels=("DRAFT",))
        return {"id": "m1"}
    send("arun@newco.com", "Hello", "…")
    v = at.ledger.last().verification
    assert v.level == "unverified" and "label:SENT" in v.evidence["failed"]


def test_gmail_wrong_recipient_or_subject_is_unverified(at, gmail):
    @at.action(system="gmail", verb="send", target="to")
    def send(to, subject, body):
        gmail.msgs["m1"] = gmail_msg("m1", "else@x.com", "Other")
        return {"id": "m1"}
    send("arun@newco.com", "Hello", "…")
    failed = at.ledger.last().verification.evidence["failed"]
    assert "recipient:arun@newco.com" in failed and "subject" in failed


def test_gmail_cc_counts_and_multiple_recipients(at, gmail):
    @at.action(system="gmail", verb="send")
    def send(to, cc, subject):
        gmail.msgs["m1"] = gmail_msg("m1", "a@x.com, b@x.com", subject, cc="c@x.com")
        return {"id": "m1"}
    send(["a@x.com", "b@x.com"], "c@x.com", "S")
    assert at.ledger.last().verification.level == "verified"


def test_gmail_reply_thread_mismatch(at, gmail):
    @at.action(system="gmail", verb="reply")
    def reply(message_id, body):
        gmail.msgs["m2"] = gmail_msg("m2", "ram@acme.com", "Re", thread="OTHER")
        return {"id": "m2", "threadId": "t1", "to": "ram@acme.com"}
    reply("m0", "thanks")
    v = at.ledger.last().verification
    assert v.level == "unverified" and "threadId" in v.evidence["failed"]


def test_gmail_missing_message_degrades_to_acknowledged(at, gmail):
    @at.action(system="gmail", verb="send")
    def send(to):
        return {"id": "never-stored"}
    send("a@x.com")
    v = at.ledger.last().verification
    assert v.level == "acknowledged" and "fetch failed" in v.evidence["check_error"]


def test_gmail_draft_and_labels(at, gmail):
    @at.action(system="gmail", verb="create", target="draft")
    def draft(to, subject):
        gmail.drafts_["d1"] = {"id": "d1", "message": gmail_msg("m9", to, subject, labels=("DRAFT",))}
        return {"id": "d1", "message": {"id": "m9"}}
    draft("a@x.com", "S")
    assert at.ledger.last().verification.level == "verified"

    @at.action(system="gmail", verb="update")
    def archive(message_id, remove_labels, add_labels=None):
        gmail.msgs[message_id] = {"id": message_id, "labelIds": ["STARRED"]}
        return {"id": message_id}
    archive("m5", ["INBOX"], ["STARRED"])
    v = at.ledger.last().verification
    assert v.level == "verified" and v.evidence["checks"] == {"label:+STARRED": True, "label:-INBOX": True}

    @at.action(system="gmail", verb="update")
    def archive_fail(message_id, remove_labels):
        gmail.msgs[message_id] = {"id": message_id, "labelIds": ["INBOX"]}
        return {"id": message_id}
    archive_fail("m6", ["INBOX"])
    assert at.ledger.last().verification.level == "unverified"


def test_gmail_without_reader_falls_back_to_ack(gmail):
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate())
    @at.action(system="gmail", verb="send")
    def send(to):
        return {"id": "m1"}
    send("a@x.com")
    assert at.ledger.last().verification.level == "acknowledged" and at.ledger.last().verification.method == "ack"


def test_per_action_reader_override(gmail):
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate())
    @at.action(system="gmail", verb="send", reader=gmail)
    def send(to, subject):
        gmail.msgs["m1"] = gmail_msg("m1", to, subject)
        return {"id": "m1"}
    send("a@x.com", "S")
    assert at.ledger.last().verification.level == "verified"


# ── Slack ─────────────────────────────────────────────────────────────────────
class FakeSlack:
    def __init__(self):
        self.msgs, self.channels = {}, {}

    def conversations_history(self, channel, latest, inclusive, limit):
        m = self.msgs.get((channel, latest))
        return {"ok": True, "messages": [m] if m else []}

    def conversations_replies(self, channel, ts, limit):
        m = self.msgs.get((channel, ts))
        return {"ok": True, "messages": [m] if m else []}

    def conversations_info(self, channel):
        c = self.channels.get(channel)
        return {"ok": bool(c), "channel": c, "error": None if c else "channel_not_found"}


@pytest.fixture
def slack():
    return FakeSlack()


@pytest.fixture
def ats(slack):
    return Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), readers={"slack": slack})


def test_slack_post_message_verified_and_text_mismatch(ats, slack):
    @ats.action(system="slack", verb="send", target="channel")
    def post(channel, text):
        slack.msgs[(channel, "1.1")] = {"ts": "1.1", "text": text, "channel": channel}
        return {"ok": True, "channel": channel, "ts": "1.1"}
    post("C1", "hello team")
    v = ats.ledger.last().verification
    assert v.level == "verified" and v.evidence["fields"]["text"]["ok"]

    @ats.action(system="slack", verb="send")
    def post_bad(channel, text):
        slack.msgs[(channel, "1.2")] = {"ts": "1.2", "text": "something else"}
        return {"ok": True, "channel": channel, "ts": "1.2"}
    post_bad("C1", "hello")
    assert ats.ledger.last().verification.level == "unverified"


def test_slack_message_not_found_degrades(ats):
    @ats.action(system="slack", verb="send")
    def post(channel, text):
        return {"ok": True, "channel": channel, "ts": "9.9"}
    post("C1", "x")
    v = ats.ledger.last().verification
    assert v.level == "acknowledged" and "nothing to compare" in v.evidence["check_error"]


def test_slack_create_channel(ats, slack):
    @ats.action(system="slack", verb="create", target="channel")
    def mk(name):
        slack.channels["C9"] = {"id": "C9", "name": name.lstrip("#"), "is_private": False}
        return {"ok": True, "channel": {"id": "C9", "name": name}}
    mk("#launch")
    assert ats.ledger.last().verification.level == "verified"


# ── HubSpot ───────────────────────────────────────────────────────────────────
class FakeHubSpot:
    def __init__(self):
        self.objects = {}
        self.crm = self
        self.objects_ = self
        self.basic_api = self

    @property
    def objects(self):  # noqa: F811 - crm.objects.basic_api
        return self

    @objects.setter
    def objects(self, v):
        self.store = v

    def get_by_id(self, object_type, object_id, properties=None):
        data = self.store.get((object_type, str(object_id)))
        if data is None:
            raise Exception("(404) Not Found")
        return {"id": str(object_id), "properties": {k: v for k, v in data.items() if not properties or k in properties}}


@pytest.fixture
def hs():
    return FakeHubSpot()


@pytest.fixture
def ath(hs):
    return Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), readers={"hubspot": hs})


def test_hubspot_create_and_update_field_compare(ath, hs):
    @ath.action(system="hubspot", verb="create", target="deal")
    def create_deal(properties):
        hs.store[("deals", "777")] = dict(properties)
        return {"id": "777", "properties": properties}
    create_deal({"dealname": "Acme", "amount": "1000"})
    v = ath.ledger.last().verification
    assert v.level == "verified" and set(v.evidence["fields"]) == {"id", "dealname", "amount"}

    @ath.action(system="hubspot", verb="update", target="deal")
    def update_deal(deal_id, dealname):
        hs.store[("deals", deal_id)]["dealname"] = "SOMETHING ELSE"  # the vendor "lost" the update
        return {"id": deal_id}
    update_deal("777", "Acme Corp")
    v = ath.ledger.last().verification
    assert v.level == "unverified" and v.evidence["failed"] == ["dealname"]


def test_hubspot_object_type_from_params(ath, hs):
    @ath.action(system="hubspot", verb="update")
    def upd(object_type, object_id, properties):
        hs.store[(object_type, object_id)] = dict(properties)
        return {"id": object_id}
    upd("contacts", "5", {"email": "A@B.com"})
    v = ath.ledger.last().verification
    assert v.level == "verified" and v.evidence["fields"]["email"]["ok"]


def test_hubspot_missing_record_is_unverified(ath):
    @ath.action(system="hubspot", verb="create", target="contact")
    def create(properties):
        return {"id": "nope"}
    create({"email": "x@y.com"})
    v = ath.ledger.last().verification
    assert v.level == "acknowledged" and "nothing to compare" in v.evidence["check_error"]


def test_hubspot_existence_only_is_acknowledged(ath, hs):
    hs.store[("deals", "1")] = {"other": "x"}
    @ath.action(system="hubspot", verb="update", target="deal")
    def touch(deal_id):
        return {"id": deal_id}
    touch("1")
    v = ath.ledger.last().verification
    assert v.level == "acknowledged" and v.evidence["exists"] and "no intended field" in v.evidence["detail"]


# ── registry ─────────────────────────────────────────────────────────────────
def test_recipe_lookup_and_driver_support():
    assert recipes.find(D(system="gmail", verb="send"), {}).name == "gmail.send"
    assert recipes.find(D(system="gmail", verb="update", params={"add_labels": ["X"]}), {}).name == "gmail.labels"
    assert recipes.find(D(system="gmail", verb="update", params={"foo": 1}), {}) is None
    assert recipes.find(D(system="slack", verb="create", target="channel"), {}).name == "slack.channel"
    assert recipes.find(D(system="hubspot", verb="create", target="deal"), {}).name == "hubspot.object"
    assert recipes.find(D(system="hubspot", verb="create"), {}) is None
    drv = RecipeDriver({"gmail": lambda p, q: {}})
    assert drv.supports(D(system="gmail", verb="send")) and not drv.supports(D(system="slack", verb="send"))
    assert len(recipes.all_recipes()) >= 6


def test_verify_direct_with_driver_list():
    class G:
        def users(self):
            return self
        def messages(self):
            return self
        def get(self, **kw):
            return type("R", (), {"execute": lambda s: gmail_msg("m1", "a@x.com", "S")})()
    d = D(system="gmail", verb="send", params={"to": "a@x.com", "subject": "S"}).with_result({"id": "m1"})
    assert verify(d, {"id": "m1"}, drivers=[RecipeDriver({"gmail": G()})]).level == "verified"
