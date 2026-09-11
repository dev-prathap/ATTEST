import json

import pytest

from attest.descriptor import ActionDescriptor as D
from attest.ledger import GENESIS, LedgerEntry, SqliteLedger, preview


def entry(i=0, **kw):
    d = D(system="gmail", verb="send", params={"to": f"u{i}@x.com", "body": "secret body"}, agent="a", run_id="r1")
    return LedgerEntry.from_descriptor(d, decision="act", risk_tier="high", **kw)


def test_append_assigns_seq_and_links(ledger):
    e1, e2 = ledger.append(entry(1)), ledger.append(entry(2))
    assert (e1.seq, e2.seq) == (1, 2)
    assert e1.prev_hash == GENESIS and e2.prev_hash == e1.hash
    assert ledger.verify_chain().ok and ledger.count() == 2


def test_tamper_payload_breaks_chain(ledger):
    for i in range(3):
        ledger.append(entry(i))
    ledger._cx.execute("UPDATE ledger SET payload = replace(payload, '\"decision\":\"act\"', '\"decision\":\"ask\"') WHERE seq = 2")
    rep = ledger.verify_chain()
    assert not rep.ok and rep.broken_at == 2 and "payload altered" in rep.problems[0]


def test_delete_row_breaks_chain(ledger):
    for i in range(3):
        ledger.append(entry(i))
    ledger._cx.execute("DELETE FROM ledger WHERE seq = 2")
    rep = ledger.verify_chain()
    assert not rep.ok and rep.broken_at == 3


def test_rewrite_hash_alone_breaks_chain(ledger):
    for i in range(2):
        ledger.append(entry(i))
    ledger._cx.execute("UPDATE ledger SET hash = 'f' * 64 WHERE seq = 1")
    rep = ledger.verify_chain()
    assert not rep.ok and rep.broken_at == 1


def test_recomputed_forgery_still_breaks_the_next_link(ledger):
    """Even a forger who recomputes seq 1's hashes cannot fix seq 2's prev_hash without rewriting it too."""
    from attest.ledger import hashchain
    for i in range(2):
        ledger.append(entry(i))
    row = ledger._rows()[0]
    row["payload"]["decision"] = "ask"
    ph = hashchain.payload_hash(row["payload"])
    h = hashchain.entry_hash(GENESIS, 1, ph)
    ledger._cx.execute("UPDATE ledger SET payload=?, payload_hash=?, hash=? WHERE seq=1",
                       (json.dumps(row["payload"], sort_keys=True, separators=(",", ":")), ph, h))
    rep = ledger.verify_chain()
    assert not rep.ok and rep.broken_at == 2


def test_raw_params_never_stored(ledger):
    ledger.append(entry())
    raw = ledger._cx.execute("SELECT payload FROM ledger").fetchone()[0]
    assert "secret body" not in raw and "u0@x.com" in raw  # `to` is allow-listed, body is not


def test_preview_allowlist():
    assert preview({"to": "a@b.com", "body": "x" * 500, "deal_id": 7}) == {"to": "a@b.com", "deal_id": 7}
    assert preview("y" * 200).endswith("…")
    assert preview(None) is None


def test_entries_filters_and_get(ledger):
    ledger.append(entry(1))
    e = ledger.append(entry(2))
    assert len(ledger.entries(run_id="r1")) == 2 and ledger.entries(run_id="nope") == []
    assert ledger.get(e.action_id).seq == 2 and ledger.last().seq == 2
    assert ledger.entries(limit=1, newest_first=True)[0].seq == 2


def test_export_json_and_csv(ledger):
    ledger.append(entry())
    data = json.loads(ledger.export("json"))
    assert data[0]["seq"] == 1 and data[0]["hash"]
    assert ledger.export("csv").splitlines()[0].startswith("seq,created_at")
    with pytest.raises(ValueError):
        ledger.export("xml")


def test_file_backed_ledger_persists(tmp_path):
    p = tmp_path / "l.sqlite"
    SqliteLedger(p).append(entry())
    again = SqliteLedger(p)
    assert again.count() == 1 and again.verify_chain().ok


def test_concurrent_appends_keep_chain(ledger):
    import threading
    def work(n):
        for i in range(20):
            ledger.append(entry(n * 100 + i))
    ts = [threading.Thread(target=work, args=(n,)) for n in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert ledger.count() == 80 and ledger.verify_chain().ok
