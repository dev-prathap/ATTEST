import io

import pytest

from attest import ActionRefused, ActionRejected, Attest, AutoGate, ConsoleGate, PolicyEngine, SqliteLedger


def test_decorated_function_runs_and_records(client, ledger):
    @client.action(system="hubspot", verb="update", target="deal_id")
    def update_deal(deal_id, dealname):
        return {"id": deal_id}

    assert update_deal("123", dealname="Acme") == {"id": "123"}
    e = ledger.last()
    assert e.descriptor["system"] == "hubspot" and e.descriptor["target"] == "123"
    assert e.decision == "act" and e.confirm.status == "not_required"
    assert e.execution.status == "done" and e.verification.level == "acknowledged"
    assert e.params_preview == {"deal_id": "123", "dealname": "Acme"}
    assert e.agent == "test-agent@v1" and e.actor == "ram@acme.com"


def test_ask_goes_through_gate_and_records_approver(client, ledger, gate):
    @client.action(system="gmail", verb="send", target="to")
    def send(to, subject):
        return {"id": "m1"}

    send("arun@newco.com", "hi")
    e = ledger.last()
    assert e.decision == "ask" and e.confirm.status == "approved" and e.confirm.approver == "tester"
    assert e.target_class == "external" and gate.requests[0].reasons


def test_rejection_raises_and_records_without_executing(ledger):
    at = Attest(ledger=ledger, gate=AutoGate("rejected", approver="bob", ), agent="a")
    calls = []

    @at.action(system="slack", verb="delete")
    def rm(channel):
        calls.append(channel)

    with pytest.raises(ActionRejected):
        rm("C1")
    assert calls == [] and ledger.last().confirm.status == "rejected" and ledger.last().execution is None


def test_refusal_raises_and_records(ledger, gate):
    at = Attest(ledger=ledger, gate=gate, policy=PolicyEngine.from_yaml(
        "policies:\n  - match: { target_domain: [competitor.com] }\n    decision: refuse\n"))

    @at.action(system="gmail", verb="send")
    def send(to):
        raise AssertionError("must not run")

    with pytest.raises(ActionRefused) as ei:
        send(to="eve@competitor.com")
    assert ledger.last().decision == "refuse" and "competitor.com" in ei.value.reasons[0]


def test_edits_at_confirm_change_what_runs(ledger):
    at = Attest(ledger=ledger, gate=AutoGate("approved", edits={"subject": "edited"}), actor="a@acme.com")

    @at.action(system="gmail", verb="send")
    def send(to, subject):
        return subject

    assert send(to="x@ext.com", subject="orig") == "edited"
    e = ledger.last()
    assert e.confirm.status == "edited" and e.confirm.edits == {"subject": "edited"} and e.params_preview["subject"] == "edited"


def test_execution_failure_is_recorded_and_reraised(client, ledger):
    @client.action(system="internal", verb="update")
    def boom(x):
        raise RuntimeError("vendor down")

    with pytest.raises(RuntimeError):
        boom(1)
    e = ledger.last()
    assert e.execution.status == "failed" and "vendor down" in e.execution.error
    assert e.verification.level == "attested-only"


def test_custom_verify_hook(client, ledger):
    @client.action(system="x", verb="update", verify=lambda r: r["ok"])
    def f(a):
        return {"ok": a}

    f(True)
    assert ledger.last().verification.level == "verified-custom"
    f(False)
    assert ledger.last().verification.level == "unverified"


async def test_async_function(client, ledger):
    @client.action(system="x", verb="update")
    async def f(a):
        return {"id": a}

    assert await f(5) == {"id": 5}
    assert ledger.last().verification.level == "acknowledged"


async def test_async_custom_verify_and_gate(client, ledger):
    async def chk(r):
        return r["id"] == 1

    @client.action(system="gmail", verb="send", verify=chk)
    async def f(to):
        return {"id": 1}

    await f("x@ext.com")
    e = ledger.last()
    assert e.confirm.status == "approved" and e.verification.level == "verified-custom"


def test_run_context_groups_entries(client, ledger):
    @client.action(system="x", verb="get")
    def g(i):
        return i

    with client.run("run-42", actor="alice@acme.com"):
        g(1)
        g(2)
    g(3)
    assert [e.run_id for e in ledger.entries()] == ["run-42", "run-42", None]
    assert ledger.entries()[0].actor == "alice@acme.com" and ledger.entries()[2].actor == "ram@acme.com"


def test_inference_from_function_name_and_url(client, ledger):
    @client.action
    def send_email(to, body):
        return {"id": 1}

    send_email("bob@acme.com", "hi")
    assert ledger.last().descriptor["verb"] == "send" and ledger.last().descriptor["system"] == "unknown"

    @client.action(method="POST", url="https://api.someweirdcrm.io/v2/leads")
    def create_lead(name):
        return {"id": "L-991"}

    create_lead("x")
    d = ledger.last().descriptor
    assert (d["system"], d["verb"], d["target"], d["source"]) == ("someweirdcrm", "create", "leads", "url")


def test_target_callable_and_literal(client, ledger):
    @client.action(system="x", verb="get", target=lambda a: f"row:{a['i']}")
    def g(i):
        return i

    g(7)
    assert ledger.last().descriptor["target"] == "row:7"

    @client.action(system="x", verb="get", target="the-thing")
    def h(i):
        return i

    h(1)
    assert ledger.last().descriptor["target"] == "the-thing"


def test_params_reshaper_only_affects_the_record(client, ledger):
    @client.action(system="x", verb="update", params=lambda p: {"n": len(p["blob"])})
    def up(blob):
        return {"id": 1, "size": len(blob)}

    assert up("abc")["size"] == 3
    assert ledger.last().params_preview == {} and ledger.last().params_hash != ""


def test_api_only_attest(client, ledger):
    e = client.attest(system="n8n", verb="send", target="x@ext.com", result={"id": "m1"})
    assert e.decision == "recorded" and e.verification.level == "acknowledged" and e.target_class == "external"
    e = client.attest(system="n8n", verb="send", verified=True, evidence={"message_id": "m1"})
    assert e.verification.level == "verified-custom"
    e = client.attest(system="n8n", verb="send", verified=False, evidence={"why": "bounced"})
    assert e.verification.level == "unverified"
    e = client.attest(system="n8n", verb="send", error="timeout")
    assert e.execution.status == "failed"
    assert ledger.verify_chain().ok


def test_chain_intact_after_full_flow(client, ledger):
    @client.action(system="gmail", verb="send")
    def s(to):
        return {"id": 1}

    for i in range(5):
        s(f"u{i}@ext.com")
    assert ledger.count() == 5 and ledger.verify_chain().ok


def test_console_gate_non_interactive_rejects(ledger):
    at = Attest(ledger=ledger, gate=ConsoleGate(stdin=io.StringIO("y\n"), stdout=io.StringIO()), agent="a")

    @at.action(system="gmail", verb="send")
    def s(to):
        return 1

    with pytest.raises(ActionRejected):
        s("x@ext.com")
    assert "non-interactive" in ledger.last().confirm.note


def test_console_gate_interactive_paths(ledger):
    def make(answers):
        stdin = io.StringIO(answers)
        stdin._attest_force_interactive = True
        return Attest(ledger=ledger, gate=ConsoleGate(stdin=stdin, stdout=io.StringIO(), approver="ram"), agent="a")

    at = make("y\n")
    assert at.action(system="gmail", verb="send")(lambda to: to)("x@ext.com") == "x@ext.com"
    assert ledger.last().confirm.approver == "ram"
    at = make("e\n{\"to\": \"y@ext.com\"}\n")
    assert at.action(system="gmail", verb="send")(lambda to: to)("x@ext.com") == "y@ext.com"
    at = make("maybe\nnot json\n{\"to\": 1}\n")  # bad answer, then edit with bad json, then good
    out = io.StringIO()
    at.gate.stdout = out
    at.gate.stdin = io.StringIO("zzz\ne\nnot json\ne\n{\"to\": \"z@ext.com\"}\n")
    at.gate.stdin._attest_force_interactive = True
    assert at.action(system="gmail", verb="send")(lambda to: to)("x@ext.com") == "z@ext.com"
    assert "answer y, n or e" in out.getvalue() and "invalid JSON" in out.getvalue()
    at = make("n\n")
    with pytest.raises(ActionRejected):
        at.action(system="gmail", verb="send")(lambda to: to)("x@ext.com")


def test_module_level_default_client(tmp_path, monkeypatch):
    import attest
    monkeypatch.setenv("ATTEST_LEDGER", str(tmp_path / "l.sqlite"))
    monkeypatch.setenv("ATTEST_AUTO_APPROVE", "1")
    attest.configure(agent="mod")

    @attest.action(system="gmail", verb="send")
    def s(to):
        return {"id": 1}

    with attest.run("r9"):
        s("x@ext.com")
    e = attest.default().ledger.last()
    assert e.run_id == "r9" and e.confirm.approver == "env" and e.agent == "mod"
    assert SqliteLedger(tmp_path / "l.sqlite").count() == 1
