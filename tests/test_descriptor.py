from attest.descriptor import ActionDescriptor, canonical_json, short_hash


def test_params_hash_is_deterministic_and_order_independent():
    a = ActionDescriptor(system="gmail", verb="send", params={"to": "x@y.com", "subject": "hi"})
    b = ActionDescriptor(system="gmail", verb="send", params={"subject": "hi", "to": "x@y.com"})
    assert a.params_hash == b.params_hash == short_hash({"subject": "hi", "to": "x@y.com"})
    assert len(a.params_hash) == 16


def test_params_hash_changes_with_content():
    a = ActionDescriptor(params={"to": "x@y.com"})
    b = ActionDescriptor(params={"to": "z@y.com"})
    assert a.params_hash != b.params_hash


def test_defaults_are_unknown_write():
    d = ActionDescriptor()
    assert d.system == "unknown" and d.verb == "write" and d.is_write
    assert d.id.startswith("act_")


def test_read_verbs_are_not_writes():
    assert not ActionDescriptor(verb="search").is_write
    assert ActionDescriptor(verb="pay").is_write


def test_to_ledger_never_carries_raw_params_or_result():
    d = ActionDescriptor(system="gmail", verb="send", params={"body": "secret"}, result={"id": "1", "body": "secret"})
    stored = d.to_ledger()
    assert "params" not in stored and "result" not in stored
    assert stored["params_hash"] == d.params_hash
    assert "secret" not in canonical_json(stored)


def test_with_result_does_not_mutate():
    d = ActionDescriptor()
    d2 = d.with_result({"id": 1})
    assert d.result is None and d2.result == {"id": 1} and d2.id == d.id


def test_canonical_json_handles_non_json_types():
    from datetime import datetime
    assert canonical_json({"t": datetime(2026, 1, 1)}) == '{"t":"2026-01-01 00:00:00"}'
