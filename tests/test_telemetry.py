from attest import Attest, AutoGate, SqliteLedger
from attest.telemetry import Telemetry


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("ATTEST_TELEMETRY", raising=False)
    t = Telemetry()
    t.record(decision="act", level="verified", system="gmail")
    assert not t.enabled and not t.counts and not t.flush()


def test_counts_only_and_flush(monkeypatch):
    sent = []
    t = Telemetry(enabled=True, post=lambda url, body: sent.append((url, body)))
    for _ in range(50):
        t.record(decision="ask", level="acknowledged", system="someweirdcrm", entry_point="langgraph")
    assert len(sent) == 1
    import json
    body = json.loads(sent[0][1])
    assert body["counts"]["system:other"] == 50 and body["counts"]["entry:langgraph"] == 50 and "target" not in json.dumps(body)
    assert not t.counts


def test_client_records_when_enabled(monkeypatch):
    monkeypatch.setenv("ATTEST_TELEMETRY", "1")
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate())
    at.telemetry._post = lambda url, body: None

    @at.action(system="gmail", verb="get")
    def g(i):
        return i

    g(1)
    assert at.telemetry.counts["decision:act"] == 1 and at.telemetry.counts["system:gmail"] == 1


def test_flush_failure_never_raises():
    def boom(url, body):
        raise OSError("down")
    t = Telemetry(enabled=True, post=boom)
    t.record(decision="act", level="verified", system="gmail")
    assert t.flush() is False and t.counts["actions"] == 1
