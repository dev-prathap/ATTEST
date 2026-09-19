import json

import pytest

from attest import Attest, AutoGate, SqliteLedger
from attest.cli import main as cli
from attest.descriptor import ActionDescriptor as D
from attest.ledger import LedgerEntry
from attest.ledger import checkpoints as cps
from attest.ledger.exports import eu_ai_act_pack, ietf_records


def fill(L, n=5):
    for i in range(n):
        L.append(LedgerEntry.from_descriptor(D(system="x", verb="get", params={"i": i}), decision="act", risk_tier="low"))


def test_checkpoint_sign_and_verify():
    L = SqliteLedger(":memory:", signing_key="k1")
    assert L.checkpoint() is None
    fill(L, 3)
    cp = L.checkpoint()
    assert cp.seq == 3 and cp.signature.startswith("v1=") and cp.key_id == cps.key_id("k1")
    assert cps.verify_signature(cp, "k1") and not cps.verify_signature(cp, "k2")
    assert not cps.verify_signature(cps.sign(1, "h", key=None), "k1")  # unsigned
    assert [c.seq for c in L.checkpoints()] == [3]


def test_prune_keeps_chain_verifiable():
    L = SqliteLedger(":memory:", signing_key="k1")
    fill(L, 6)
    assert L.prune(before_seq=4) == 3
    assert L.count() == 3 and L.verify_chain().ok and L.verify_chain().checked == 6
    assert L.checkpoints()[0].seq == 3
    assert L.prune(before_seq=100) == 2  # never prunes the head
    assert L.count() == 1 and L.verify_chain().ok
    with pytest.raises(ValueError):
        L.prune()


def test_prune_by_age_and_missing_anchor_detected():
    L = SqliteLedger(":memory:")
    fill(L, 3)
    assert L.prune(older_than_days=0) == 2  # everything before now except the head
    assert L.verify_chain().ok
    L._cx.execute("DELETE FROM checkpoint")
    rep = L.verify_chain()
    assert not rep.ok and "no checkpoint" in rep.problems[0]


def test_tamper_after_prune_still_detected():
    L = SqliteLedger(":memory:")
    fill(L, 5)
    L.prune(before_seq=3)
    L._cx.execute("UPDATE ledger SET payload = replace(payload, '\"decision\":\"act\"', '\"decision\":\"ask\"') WHERE seq = 4")
    assert L.verify_chain().broken_at == 4


def flow():
    at = Attest(ledger=SqliteLedger(":memory:", signing_key="k"), gate=AutoGate(approver="ram"), actor="ram@acme.com", agent="a@v1")

    @at.action(system="gmail", verb="send", target="to", verify=lambda r: r.get("ok", True))
    def send(to, ok=True):
        return {"id": "m1", "ok": ok}

    with at.run("run-1"):
        send("x@ext.com")
        send("y@acme.com", ok=False)
    from attest import ActionRefused
    from attest.policy import PolicyEngine
    at.policy = PolicyEngine.from_yaml("policies:\n  - match: {verb: delete}\n    decision: refuse\n")
    with pytest.raises(ActionRefused):
        at.action(system="x", verb="delete")(lambda a: 1)(1)
    return at


def test_ietf_records_shape_and_chaining():
    at = flow()
    recs = ietf_records(at.ledger.entries())
    assert [r["outcome"] for r in recs] == ["success", "failure", "denied"]
    assert [r["trust_level"] for r in recs] == ["L2", "L0", "L0"]
    assert recs[0]["parent_record_id"] is None and recs[0]["prev_hash"] is None
    assert recs[1]["parent_record_id"] == recs[0]["record_id"] and len(recs[1]["prev_hash"]) == 64
    assert recs[0]["human_override"]["approver"] == "ram" and recs[0]["action_type"] == "tool_call"
    assert recs[1]["deny_reasons"][0].startswith("read-back contradicted") and recs[2]["deny_reasons"]
    assert recs[0]["input_hash"] == at.ledger.entries()[0].params_hash and recs[0]["record_phase"] == "post_execution"
    assert recs[2]["record_phase"] == "pre_execution" and recs[0]["session_id"] == recs[1]["session_id"]
    assert set(recs[0]) >= {"record_id", "timestamp", "agent_id", "agent_version", "session_id", "action_type",
                            "action_detail", "outcome", "trust_level", "parent_record_id", "prev_hash", "record_phase"}
    lines = at.ledger.export("ietf").splitlines()
    assert len(lines) == 3 and json.loads(lines[2])["outcome"] == "denied"


def test_eu_ai_act_pack():
    at = flow()
    at.ledger.checkpoint()
    pack = json.loads(at.ledger.export("eu-ai-act"))
    assert pack["format"] == "attest-eu-ai-act-event-log/1" and pack["period"]["events"] == 3
    assert pack["summary"]["by_level"] == {"verified-custom": 1, "unverified": 1, "attested-only": 1}
    assert pack["summary"]["human_decisions"] == {"approved": 2}
    ev = pack["events"][0]
    assert ev["human_oversight"]["approver"] == "ram" and ev["integrity"]["hash"] and "body" not in json.dumps(ev)
    assert pack["integrity"]["checkpoints"][0]["seq"] == 3 and pack["integrity"]["chain"]["ok"]
    assert pack["manifest"]["signature"].startswith("v1=") and set(pack["field_map"]) >= {"human_oversight", "integrity"}
    direct = eu_ai_act_pack(at.ledger.entries(), signing_key=None)
    assert direct["manifest"]["signature"] is None


def test_cli_checkpoint_prune_export(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ATTEST_LEDGER_KEY", "cli-key")
    p = str(tmp_path / "l.sqlite")
    fill(SqliteLedger(p), 4)
    assert cli(["--ledger", p, "checkpoint"]) == 0
    assert json.loads(capsys.readouterr().out)["signature"].startswith("v1=")
    assert cli(["--ledger", p, "prune", "--older-than-days", "0"]) == 0
    assert "pruned 3" in capsys.readouterr().out
    assert cli(["--ledger", p, "export", "--format", "ietf"]) == 0
    assert json.loads(capsys.readouterr().out.strip())["trust_level"] == "L0"
    assert cli(["--ledger", p, "export", "--format", "eu-ai-act"]) == 0
    assert json.loads(capsys.readouterr().out)["integrity"]["checkpoints"]


def test_verify_chain_since_checkpoint_is_bounded():
    L = SqliteLedger(":memory:", signing_key="k")
    fill(L, 6)
    L.checkpoint()                       # pins seq 6
    fill(L, 3)                           # seqs 7-9
    full, bounded = L.verify_chain(), L.verify_chain(since_checkpoint=True)
    assert full.ok and full.checked == 9
    assert bounded.ok and bounded.checked == 9   # counts through the anchor, only reads rows after it
    L._cx.execute("UPDATE ledger SET payload = replace(payload, '\"decision\":\"act\"', '\"decision\":\"ask\"') WHERE seq = 8")
    assert L.verify_chain(since_checkpoint=True).broken_at == 8      # still catches tampering after the anchor
    assert L.verify_chain().broken_at == 8
    assert SqliteLedger(":memory:").verify_chain(since_checkpoint=True).ok   # no checkpoint ⇒ falls back
