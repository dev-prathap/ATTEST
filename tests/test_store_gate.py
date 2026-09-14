import asyncio
import threading
import time

import pytest

from attest import ActionPending, ActionRejected, Attest, AttestError, PendingStore, SqliteLedger, StoreGate
from attest.descriptor import ActionDescriptor as D
from attest.gate import ConfirmDecision, ConfirmRequest


@pytest.fixture
def store():
    return PendingStore(":memory:")


def req(**kw):
    return ConfirmRequest("a1", D(system="gmail", verb="send", params={"to": "x@ext.com", "body": "secret"}), ["why"], "high", **kw)


# ── store ─────────────────────────────────────────────────────────────────────
def test_store_create_get_decide_first_wins(store):
    r = req()
    tok = store.create(r)
    row = store.get(tok)
    assert row["status"] == "pending" and row["descriptor"]["params"]["to"] == "x@ext.com" and row["id"] == r.id
    assert store.decision(r.id).pending
    assert store.decide(r.id, ConfirmDecision("approved", "ram", channel="web"))
    assert not store.decide(r.id, ConfirmDecision("rejected", "bob"))  # already decided
    dec = store.decision(tok)
    assert dec.status == "approved" and dec.approver == "ram" and dec.channel == "web"
    assert store.pending() == [] and store.recent()[0]["approver"] == "ram"


def test_store_request_roundtrip_and_meta(store):
    r = req(approvers=["finance"], hold=True)
    store.create(r, meta={"slack_ts": "1.2"})
    back = store.request(r.resume_token)
    assert back.id == r.id and back.approvers == ["finance"] and back.hold and back.descriptor.params == r.descriptor.params
    store.set_meta(r.id, slack_channel="C1")
    assert store.get(r.id)["meta"] == {"slack_ts": "1.2", "slack_channel": "C1"}
    assert store.get("nope") is None and store.request("nope") is None and store.decision("nope") is None


def test_store_ttl_expiry(store):
    r = req()
    store.create(r, ttl_s=-1)  # already overdue
    assert store.get(r.id)["status"] == "expired" and store.decision(r.id).status == "expired"


def test_store_wait_returns_when_decided_from_another_thread(store):
    r = req()
    store.create(r)
    threading.Timer(0.2, lambda: store.decide(r.id, ConfirmDecision("approved", "ram"))).start()
    t0 = time.monotonic()
    dec = store.wait(r.id, timeout_s=5, poll_s=0.05)
    assert dec.status == "approved" and time.monotonic() - t0 < 2


def test_store_wait_timeout_expires(store):
    r = req()
    store.create(r)
    assert store.wait(r.id, timeout_s=0.2, poll_s=0.05).status == "expired"
    assert store.wait("unknown", timeout_s=0.1).status == "rejected"


def test_store_file_backed_shared_between_instances(tmp_path):
    p = tmp_path / "l.sqlite"
    a, b = PendingStore(p), PendingStore(p)
    r = req()
    a.create(r)
    assert b.get(r.id)["status"] == "pending"
    b.decide(r.id, ConfirmDecision("approved", "x"))
    assert a.decision(r.id).status == "approved"


# ── StoreGate blocking mode ───────────────────────────────────────────────────
def test_store_gate_blocks_until_decided(store):
    gate = StoreGate(store, wait=True, timeout_s=5, poll_s=0.05)
    at = Attest(ledger=SqliteLedger(":memory:"), gate=gate, actor="ram@acme.com")

    @at.action(system="gmail", verb="send")
    def send(to):
        return {"id": "m1"}

    def approve_soon():
        time.sleep(0.15)
        store.decide(store.pending()[0]["id"], ConfirmDecision("approved", "ram", channel="web"))

    threading.Thread(target=approve_soon).start()
    assert send("x@ext.com") == {"id": "m1"}
    e = at.ledger.last()
    assert e.confirm.status == "approved" and e.confirm.approver == "ram" and e.confirm.channel == "web"


def test_store_gate_timeout_is_rejection(store):
    at = Attest(ledger=SqliteLedger(":memory:"), gate=StoreGate(store, wait=True, timeout_s=0.2, poll_s=0.05))

    @at.action(system="gmail", verb="send")
    def send(to):
        return 1

    with pytest.raises(ActionRejected):
        send("x@ext.com")
    assert at.ledger.last().confirm.status == "expired"


def test_notifier_failure_does_not_lose_request(store):
    class Broken:
        name = "broken"

        def notify(self, request, store):
            raise RuntimeError("down")

    gate = StoreGate(store, notifiers=[Broken()], wait=False)
    at = Attest(ledger=SqliteLedger(":memory:"), gate=gate)

    @at.action(system="gmail", verb="send")
    def send(to):
        return 1

    with pytest.raises(ActionPending):
        send("x@ext.com")
    assert len(store.pending()) == 1 and gate.name == "broken"


# ── pending mode + resume ─────────────────────────────────────────────────────
@pytest.fixture
def pending_client(store):
    return Attest(ledger=SqliteLedger(":memory:"), gate=StoreGate(store, wait=False), actor="ram@acme.com")


def test_pending_then_resume_same_process(pending_client, store):
    at = pending_client
    calls = []

    @at.action(system="gmail", verb="send")
    def send(to, subject):
        calls.append(subject)
        return {"id": "m1"}

    with pytest.raises(ActionPending) as ei:
        send("x@ext.com", "orig")
    tok = ei.value.resume_token
    assert calls == [] and at.ledger.last().confirm.status == "pending" and store.get(tok)["status"] == "pending"
    with pytest.raises(ActionPending):
        at.resume(tok)
    store.decide(tok, ConfirmDecision("edited", "ram", {"subject": "EDITED"}, channel="slack"))
    assert send.resume(tok) == {"id": "m1"} and calls == ["EDITED"]
    e = at.ledger.last()
    assert e.confirm.status == "edited" and e.confirm.approver == "ram" and e.resumed_from is not None
    assert e.verification.level == "acknowledged" and "resume" in e.rules_fired
    assert at.ledger.verify_chain().ok and at.ledger.count() == 2


def test_pending_then_rejected(pending_client, store):
    at = pending_client

    @at.action(system="slack", verb="delete")
    def rm(channel):
        raise AssertionError("must not run")

    with pytest.raises(ActionPending) as ei:
        rm("C1")
    store.decide(ei.value.resume_token, ConfirmDecision("rejected", "bob", note="no"))
    with pytest.raises(ActionRejected):
        at.resume(ei.value.resume_token)
    assert at.ledger.last().confirm.status == "rejected"


def test_resume_cross_process_needs_execute(store, tmp_path):
    p = tmp_path / "l.sqlite"
    at = Attest(ledger=SqliteLedger(p), gate=StoreGate(PendingStore(p), wait=False))

    @at.action(system="gmail", verb="send")
    def send(to):
        return {"id": "m1"}

    with pytest.raises(ActionPending) as ei:
        send("x@ext.com")
    tok = ei.value.resume_token
    other = Attest(ledger=SqliteLedger(p), store=PendingStore(p))  # a different process
    other.store.decide(tok, ConfirmDecision("approved", "ram"))
    with pytest.raises(AttestError, match="execute="):
        other.resume(tok)
    receipt = other.resume(tok, execute=lambda p: {"id": "from-other", "to": p["to"]})
    assert receipt.result["id"] == "from-other" and receipt.entry.confirm.status == "approved"
    with pytest.raises(AttestError, match="unknown resume token"):
        other.resume("nope")


async def test_async_pending_and_aresume(pending_client, store):
    at = pending_client

    @at.action(system="gmail", verb="send")
    async def send(to):
        await asyncio.sleep(0)
        return {"id": "m1"}

    with pytest.raises(ActionPending) as ei:
        await send("x@ext.com")
    store.decide(ei.value.resume_token, ConfirmDecision("approved", "ram"))
    assert await send.resume(ei.value.resume_token) == {"id": "m1"}


def test_custom_gate_returning_pending_is_persisted_by_core():
    class MyGate:
        name = "mine"

        def confirm(self, request):
            return ConfirmDecision("pending", channel="mine")

        async def aconfirm(self, request):
            return self.confirm(request)

    at = Attest(ledger=SqliteLedger(":memory:"), gate=MyGate(), store=PendingStore(":memory:"))

    @at.action(system="gmail", verb="send")
    def send(to):
        return {"id": 1}

    with pytest.raises(ActionPending) as ei:
        send("x@ext.com")
    assert at.store.get(ei.value.resume_token)["status"] == "pending"
    at.store.decide(ei.value.resume_token, ConfirmDecision("approved", "x"))
    assert at.resume(ei.value.resume_token).result == {"id": 1}


def test_decision_from_dict_lenient():
    assert ConfirmDecision.from_dict(True).status == "approved"
    assert ConfirmDecision.from_dict("reject").status == "rejected"
    assert ConfirmDecision.from_dict(None).status == "rejected"
    d = ConfirmDecision.from_dict({"edits": {"a": 1}, "approver": "ram"})
    assert d.status == "edited" and d.edits == {"a": 1} and d.approver == "ram"
    assert ConfirmDecision.from_dict({"status": "approve"}).status == "approved"
    assert ConfirmDecision.from_dict(42).status == "rejected"
    assert req().to_dict()["params_preview"] == {"to": "x@ext.com"}
