import pytest

from attest.descriptor import ActionDescriptor as D
from attest.policy import PolicyContext, PolicyEngine, load_yaml


@pytest.fixture
def engine():
    return PolicyEngine()


def test_r0_blocked_refuses_before_anything(engine):
    ctx = PolicyContext(org_rule=lambda d: "blocked")
    r = PolicyEngine(ctx=ctx).evaluate(D(system="gmail", verb="search"))
    assert r.decision == "refuse" and "R0" in r.rules_fired and not r.allow


def test_r0_approval_required_asks_even_for_low_risk():
    ctx = PolicyContext(org_rule=lambda d: "approval_required")
    r = PolicyEngine(ctx=ctx).evaluate(D(system="hubspot", verb="update"))
    assert r.decision == "ask" and r.requires_confirm and "R0" in r.rules_fired


def test_r1_owner_annotates_only(engine):
    r = engine.evaluate(D(system="hubspot", verb="update", actor="a@acme.com", owner="b@acme.com"))
    assert r.decision == "act" and "R1" in r.rules_fired and any("on behalf of" in x for x in r.reasons)


def test_r2_internal_recipient(engine):
    r = engine.evaluate(D(system="gmail", verb="send", params={"to": "bob@acme.com"}, actor="ram@acme.com"))
    assert r.target_class == "internal" and r.decision == "ask"  # high risk → R4 asks


def test_r2_external_recipient_hits_default_policy(engine):
    r = engine.evaluate(D(system="gmail", verb="send", params={"to": "arun@newco.com"}, actor="ram@acme.com"))
    assert r.target_class == "external" and r.decision == "ask" and "policy:external-send" in r.rules_fired


def test_r2_known_relationship():
    ctx = PolicyContext(is_known_domain=lambda dom: dom == "newco.com")
    r = PolicyEngine(ctx=ctx).evaluate(D(system="gmail", verb="send", params={"to": "arun@newco.com"}, actor="ram@acme.com"))
    assert r.target_class == "known"


def test_r2_worst_recipient_wins(engine):
    r = engine.evaluate(D(system="gmail", verb="send", params={"to": ["bob@acme.com", "eve@evil.io"]}, actor="ram@acme.com"))
    assert r.target_class == "external"


def test_r2_uses_org_domain_and_internal_domains():
    ctx = PolicyContext(org_domain=lambda: "acme.com", internal_domains={"acme.dev"})
    e = PolicyEngine(ctx=ctx)
    assert e.evaluate(D(verb="send", params={"to": "x@acme.dev"})).target_class == "internal"
    assert e.evaluate(D(verb="send", params={"to": "x@acme.com"})).target_class == "internal"


def test_r2_skips_reads(engine):
    r = engine.evaluate(D(system="gmail", verb="search", params={"to": "eve@evil.io"}))
    assert r.target_class == "none" and r.decision == "act"


def test_r2_email_in_target_field(engine):
    r = engine.evaluate(D(system="gmail", verb="send", target="arun@newco.com", actor="ram@acme.com"))
    assert r.target_class == "external"


def test_r3_placeholder_holds(engine):
    r = engine.evaluate(D(system="gmail", verb="send", params={"to": "bob@acme.com", "body": "Hi [NAME]"}, actor="ram@acme.com"))
    assert r.decision == "ask" and r.hold and "R3" in r.rules_fired


@pytest.mark.parametrize("text", ["Dear {{first_name}}", "Hello <FIRST NAME>", "Ref [ticket id]"])
def test_r3_placeholder_forms(engine, text):
    assert engine.evaluate(D(verb="send", params={"body": text})).hold


def test_r3_does_not_hold_reads(engine):
    assert not engine.evaluate(D(verb="search", params={"q": "[urgent]"})).hold


def test_r4_low_and_medium_act_high_asks(engine):
    assert engine.evaluate(D(system="x", verb="get")).decision == "act"
    assert engine.evaluate(D(system="hubspot", verb="update")).decision == "act"
    assert engine.evaluate(D(system="hubspot", verb="create")).decision == "ask"
    assert engine.evaluate(D(system="hubspot", verb="create")).risk_tier == "high"


def test_explicit_risk_override_on_descriptor(engine):
    assert engine.evaluate(D(system="hubspot", verb="create", risk="low")).decision == "act"


def test_unrecognised_write_is_high_risk(engine):
    r = engine.evaluate(D(system="someweird", verb="write"), recognised=False)
    assert r.risk_tier == "high" and r.decision == "ask"


def test_default_policy_delete_and_pay_ask(engine):
    assert engine.evaluate(D(system="slack", verb="delete")).rules_fired[-1] == "policy:destructive-or-money"
    assert engine.evaluate(D(system="stripe", verb="pay")).decision == "ask"


def test_default_policy_unknown_system_write_asks(engine):
    r = engine.evaluate(D(system="unknown", verb="write"))
    assert r.decision == "ask" and "policy:unknown-system-write" in r.rules_fired


def test_yaml_first_match_wins_and_carries_approvers():
    y = """
policies:
  - match: { system: hubspot, verb: update }
    decision: act
  - match: { verb: [delete, pay] }
    decision: ask
    approvers: [finance-leads]
  - match: { target_domain: [competitor.com] }
    decision: refuse
    reason: never contact competitors
"""
    e = PolicyEngine.from_yaml(y)
    assert e.evaluate(D(system="hubspot", verb="update")).decision == "act"
    r = e.evaluate(D(system="stripe", verb="pay"))
    assert r.decision == "ask" and r.approvers == ["finance-leads"]
    r = e.evaluate(D(system="gmail", verb="send", params={"to": "x@competitor.com"}))
    assert r.decision == "refuse" and r.reasons[-1] == "never contact competitors"


def test_yaml_glob_and_action_match():
    e = PolicyEngine.from_yaml("policies:\n  - match: { action: 'gmail.*' }\n    decision: refuse\n")
    assert e.evaluate(D(system="gmail", verb="search")).decision == "refuse"
    assert e.evaluate(D(system="slack", verb="search")).decision == "act"


def test_yaml_rejects_unknown_keys_and_bad_decisions():
    with pytest.raises(ValueError, match="unknown match keys"):
        load_yaml("policies:\n  - match: { colour: red }\n    decision: act\n")
    with pytest.raises(ValueError, match="decision must be"):
        load_yaml("policies:\n  - match: { verb: send }\n    decision: maybe\n")


def test_r3_hold_beats_yaml_act():
    e = PolicyEngine.from_yaml("policies:\n  - match: { verb: send }\n    decision: act\n")
    assert e.evaluate(D(verb="send", params={"body": "[X]"})).hold


def test_r0_blocked_beats_yaml_act():
    e = PolicyEngine.from_yaml("policies:\n  - match: { verb: send }\n    decision: act\n",
                               ctx=PolicyContext(org_rule=lambda d: "blocked"))
    assert e.evaluate(D(verb="send")).decision == "refuse"


def test_result_to_dict_is_json_ready(engine):
    d = engine.evaluate(D(system="gmail", verb="send", params={"to": "a@b.com"})).to_dict()
    assert set(d) >= {"decision", "risk_tier", "reasons", "target_class", "rules_fired", "approvers"}
