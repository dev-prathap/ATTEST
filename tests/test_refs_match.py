from attest.verify.match import MatchReport, compare_overlap, emails, equal
from attest.verify.refs import dig, first_id, resolve, resolve_all


def test_dig_paths():
    obj = {"a": {"b": [{"id": 7}]}, "id": "x"}
    assert dig(obj, "a.b[0].id") == 7 and dig(obj, "id") == "x" and dig(obj, "a.zzz") is None and dig(obj, "a.b[5]") is None


def test_resolve_result_params_default_and_literal():
    params, result = {"calendarId": "", "x": "p"}, {"id": "r1", "data": {"deal_id": 9}}
    assert resolve("$.id", params, result) == "r1"
    assert resolve("$.data.deal_id", params, result) == 9
    assert resolve("$params.x", params, result) == "p"
    assert resolve("$params.calendarId|primary", params, result) == "primary"
    assert resolve("$params.missing", params, result) is None
    assert resolve("literal", params, result) == "literal"
    assert resolve_all({"a": "$.id", "b": "lit"}, params, result) == {"a": "r1", "b": "lit"}


def test_first_id_variants():
    assert first_id({"id": "1"}) == "1"
    assert first_id({"deal_id": 5}) == "5"
    assert first_id({"data": {"id": "in"}}) == "in"
    assert first_id({"name": "x"}) is None
    assert first_id("L-1") == "L-1"
    assert first_id(None) is None
    class Obj:
        id = 12
    assert first_id(Obj()) == "12"
    assert first_id({"message_id": "m", "id": "i"}, "message_id") == "m"


def test_equal_normalises():
    assert equal("Hi  there", "hi there".title()) is False  # case matters for non-emails
    assert equal("Hi  there", " Hi there ")
    assert equal("A@B.com", "Arun <a@b.com>")
    assert equal(["a@b.com"], "x@y.com, a@b.com")
    assert equal(5, "5")
    assert equal(None, "anything")
    assert not equal("x", "y")


def test_emails():
    assert emails("Arun <a@b.com>, c@d.com") == ["a@b.com", "c@d.com"]
    assert emails(["a@b.com", "Bob <b@c.com>"]) == ["a@b.com", "b@c.com"]
    assert emails(None) == []


def test_match_report_accounting():
    r = MatchReport(matched=True)
    r.field_("subject", "Hi", "Hi")
    r.check("label:SENT", True)
    assert r.matched and r.compared == 2 and r.failed == []
    r.field_("to", "a@b.com", "c@d.com")
    assert not r.matched and r.failed == ["to"]
    ev = r.evidence()
    assert ev["compared"] == 3 and ev["failed"] == ["to"] and ev["fields"]["to"]["ok"] is False


def test_compare_overlap_uses_properties_and_skips_ids():
    r = MatchReport(matched=True)
    compare_overlap(r, {"id": "1", "dealname": "Acme", "amount": 10, "missing": "x"},
                    {"id": "1", "properties": {"dealname": "Acme", "amount": "10"}})
    assert r.matched and set(r.fields) == {"dealname", "amount"}
