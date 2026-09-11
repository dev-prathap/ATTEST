import pytest

from attest.descriptor import ActionDescriptor as D
from attest.verify import Level, ReadBackDriver, averify, verify
from attest.verify.drivers.ack import acknowledged

d = D(system="x", verb="create")


@pytest.mark.parametrize("result,ok", [
    ({"id": "L-991"}, True), ({"ts": "1.2", "channel": "C1"}, True), ({"ok": True}, True), ({"status": "sent"}, True),
    ({"status": 201}, True), ({"deal_id": 5}, True), ({"ok": False}, False), ({"error": "nope"}, False),
    ({"name": "x"}, False), ({}, False), (None, False), ("done", True), (True, True), (False, False), ([1], True), ([], False),
])
def test_ack_driver(result, ok):
    assert acknowledged(result)[0] is ok


def test_ack_object_with_status_code():
    class R:
        status_code = 204
    assert acknowledged(R()) == (True, {"status_code": 204})

    class Bad:
        status_code = 500
    assert acknowledged(Bad())[0] is False


def test_ack_evidence_has_ids_not_content():
    _, ev = acknowledged({"id": "1", "body": "secret"})
    assert ev == {"id": "1"}


def test_ladder_l1_l0():
    assert verify(d, {"id": "1"}).level == Level.ACKNOWLEDGED
    assert verify(d, {"nothing": 1}).level == Level.ATTESTED_ONLY
    assert verify(d, None).level == Level.ATTESTED_ONLY


def test_custom_true_is_l2_and_false_is_unverified():
    assert verify(d, {"id": "1"}, custom=lambda r: r["id"] == "1").level == Level.VERIFIED_CUSTOM
    v = verify(d, {"id": "1"}, custom=lambda r: False)
    assert v.level == Level.UNVERIFIED and v.matched is False


def test_custom_with_descriptor_and_evidence_tuple():
    v = verify(d, {"id": "1"}, custom=lambda r, desc: (desc.verb == "create", {"seen": r["id"]}))
    assert v.level == Level.VERIFIED_CUSTOM and v.evidence == {"seen": "1"}


def test_custom_raising_degrades_never_unverified():
    v = verify(d, {"id": "1"}, custom=lambda r: 1 / 0)
    assert v.level == Level.ACKNOWLEDGED and "ZeroDivisionError" in v.evidence["check_error"]
    v = verify(d, {"x": 1}, custom=lambda r: 1 / 0)
    assert v.level == Level.ATTESTED_ONLY


def test_custom_none_degrades():
    assert verify(d, {"id": "1"}, custom=lambda r: None).level == Level.ACKNOWLEDGED


async def test_async_custom():
    async def chk(r):
        return r["id"] == "1"
    assert (await averify(d, {"id": "1"}, custom=chk)).level == Level.VERIFIED_CUSTOM


class FakeDriver(ReadBackDriver):
    name = "fake"

    def __init__(self, fetched, matched=True, fetch_error=False):
        self.fetched, self.matched, self.fetch_error = fetched, matched, fetch_error

    def supports(self, desc):
        return desc.system == "x"

    def fetch(self, desc, result):
        if self.fetch_error:
            raise ConnectionError("down")
        return self.fetched

    def compare(self, desc, fetched):
        return self.matched, {"fetched": fetched}


def test_read_back_match_is_l3_and_beats_custom():
    v = verify(d, {"id": "1"}, custom=lambda r: False, drivers=[FakeDriver({"id": "1"})])
    assert v.level == Level.VERIFIED and v.method == "read-back:fake" and v.matched is True


def test_read_back_contradiction_is_unverified():
    v = verify(d, {"id": "1"}, drivers=[FakeDriver({"id": "1"}, matched=False)])
    assert v.level == Level.UNVERIFIED


def test_read_back_fetch_error_degrades_to_ack():
    v = verify(d, {"id": "1"}, drivers=[FakeDriver(None, fetch_error=True)])
    assert v.level == Level.ACKNOWLEDGED and "fetch failed" in v.evidence["check_error"]


def test_read_back_nothing_fetched_degrades():
    assert verify(d, {"id": "1"}, drivers=[FakeDriver(None)]).level == Level.ACKNOWLEDGED


def test_unsupported_driver_is_skipped():
    assert verify(D(system="y", verb="create"), {"id": "1"}, drivers=[FakeDriver({"id": "1"})]).level == Level.ACKNOWLEDGED
