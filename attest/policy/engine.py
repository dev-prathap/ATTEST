"""Decide: act | ask | refuse, with a risk tier and reasons (doc 02 §1).

Precedence: R0 blocked ⇒ refuse · R3 placeholder ⇒ ask (hold) · R0 approval_required ⇒ ask ·
first matching YAML rule · else R4 by risk tier. R1 and R2 only annotate (owner, target class).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from attest.descriptor import ActionDescriptor
from attest.policy import rules as R
from attest.policy.yaml_loader import PolicyDoc, Rule, default_rules, load_doc, load_doc_file


@dataclass
class PolicyResult:
    decision: str  # act | ask | refuse
    risk_tier: str  # low | medium | high | very_high
    reasons: list[str] = field(default_factory=list)
    target_class: str = "none"
    rules_fired: list[str] = field(default_factory=list)
    approvers: list[str] = field(default_factory=list)  # as written in the rule (groups or people)
    approver_members: list[str] = field(default_factory=list)  # groups resolved to people
    hold: bool = False  # needs input fixed, not just a yes

    @property
    def requires_confirm(self) -> bool:
        return self.decision == "ask"

    @property
    def allow(self) -> bool:
        return self.decision != "refuse"

    def to_dict(self) -> dict:
        return {"decision": self.decision, "risk_tier": self.risk_tier, "reasons": self.reasons,
                "target_class": self.target_class, "rules_fired": self.rules_fired, "approvers": self.approvers,
                "approver_members": self.approver_members, "hold": self.hold}


class PolicyEngine:
    def __init__(self, rules: list[Rule] | None = None, ctx: R.PolicyContext | None = None, *,
                 groups: dict[str, list[str]] | None = None, agent_rules: dict[str, list[Rule]] | None = None):
        self.rules = default_rules() if rules is None else rules
        self.ctx = ctx or R.PolicyContext()
        self.doc = PolicyDoc(self.rules, groups or {}, agent_rules or {})

    @property
    def groups(self) -> dict[str, list[str]]:
        return self.doc.groups

    @property
    def agent_rules(self) -> dict[str, list[Rule]]:
        return self.doc.agent_rules

    @classmethod
    def from_doc(cls, doc: PolicyDoc, ctx: R.PolicyContext | None = None) -> PolicyEngine:
        return cls(doc.rules, ctx, groups=doc.groups, agent_rules=doc.agent_rules)

    @classmethod
    def from_yaml(cls, text: str, ctx: R.PolicyContext | None = None) -> PolicyEngine:
        return cls.from_doc(load_doc(text), ctx)

    @classmethod
    def from_file(cls, path: str | Path, ctx: R.PolicyContext | None = None) -> PolicyEngine:
        return cls.from_doc(load_doc_file(path), ctx)

    @classmethod
    def from_env(cls, ctx: R.PolicyContext | None = None) -> PolicyEngine:
        """`ATTEST_POLICY=path.yaml`, else `./attest.yaml` if present, else the built-in default."""
        path = os.environ.get("ATTEST_POLICY") or ("attest.yaml" if Path("attest.yaml").exists() else None)
        return cls.from_file(path, ctx) if path else cls(None, ctx)

    def evaluate(self, d: ActionDescriptor, *, recognised: bool = True) -> PolicyResult:
        tier = R.risk_tier(d, recognised=recognised)
        out = PolicyResult("act", tier)

        r0 = R.r0_org_rule(d, self.ctx)
        if r0.decision == "refuse":
            return self._finish(out, "refuse", [r0])

        annotations = [R.r1_owner(d, self.ctx), R.r2_target(d, self.ctx)]
        for a in annotations:
            if a.target_class:
                out.target_class = a.target_class
            if a.reason:
                out.reasons.append(a.reason)
                out.rules_fired.append(a.rule)

        r3 = R.r3_placeholders(d, self.ctx)
        if r3.decision:
            out.hold = True
            return self._finish(out, "ask", [r3])

        if r0.decision == "ask":
            return self._finish(out, "ask", [r0])

        candidates = (self.doc.agent_rules.get(d.agent or "", []) if d.agent else []) + self.rules
        for rule in candidates:
            if rule.matches(d, tier=tier, target_class=out.target_class):
                label = f"policy:{rule.name or rule.decision}"
                out.rules_fired.append(label)
                out.reasons.append(rule.reason or f"matched policy rule {rule.name or rule.match}")
                out.approvers = list(rule.approvers)
                out.approver_members = self.doc.resolve_approvers(rule.approvers)
                out.decision = rule.decision
                return out

        return self._finish(out, None, [R.r4_risk(d, tier)])

    @staticmethod
    def _finish(out: PolicyResult, decision: str | None, fired: list[R.RuleOutcome]) -> PolicyResult:
        for f in fired:
            out.rules_fired.append(f.rule)
            if f.reason:
                out.reasons.append(f.reason)
            if f.decision and decision is None:
                decision = f.decision
        out.decision = decision or "act"
        return out
