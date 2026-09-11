"""Built-in rules R0–R4, lifted from DO `execution/policy.py` and decoupled from its database.

DO queried three tables; here they are callables on `PolicyContext` with safe defaults:
  org_rule(descriptor)      → "allowed" | "approval_required" | "blocked"   (DO: `permission` table)
  org_domain()              → the organisation's registered email domain    (DO: `org.domain`)
  is_known_domain(domain)   → a known business relationship                 (DO: `nodes` graph)

Differences from DO, on purpose (see docs/notes/do-extraction.md §1):
- R2 classifies the target (internal / known / external) onto the descriptor and does NOT refuse;
  the YAML policy decides what an external send means. The shipped default is `ask`.
- DO's `Act + requires_confirm` and `Ask` both collapse to `ask`; the reason says which.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from attest.descriptor import RISK_LABEL, ActionDescriptor
from attest.registry.systems import registered_domain
from attest.registry.verbs import risk_for

_PLACEHOLDER = re.compile(r"\[[^\]]+\]|\{\{[^}]+\}\}|<[A-Z_ ]{3,}>")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
RECIPIENT_KEYS = ("to", "cc", "bcc", "email", "emails", "attendees", "recipients", "recipient", "user", "users",
                  "share_with", "invitees", "members")
_CLASS_RANK = {"none": 0, "internal": 1, "known": 2, "external": 3}


@dataclass
class PolicyContext:
    org_rule: Callable[[ActionDescriptor], str] = lambda d: "allowed"
    org_domain: Callable[[], str | None] = lambda: None
    is_known_domain: Callable[[str], bool] = lambda domain: False
    internal_domains: set[str] = field(default_factory=set)


@dataclass
class RuleOutcome:
    """What one built-in rule concluded. `decision` is None when the rule only adds a reason."""
    rule: str
    decision: str | None = None  # act | ask | refuse
    reason: str | None = None
    target_class: str | None = None
    hold: bool = False  # `ask` that needs input fixed (placeholder), not just approval


def addresses(params: dict[str, Any], target: str | None = None) -> list[str]:
    out: list[str] = []
    for k in RECIPIENT_KEYS:
        v = params.get(k)
        vals = v if isinstance(v, list) else [v] if v else []
        for x in vals:
            out += _EMAIL.findall(str(x))
    if target:
        out += _EMAIL.findall(target)
    seen, uniq = set(), []
    for a in out:
        if a.lower() not in seen:
            seen.add(a.lower())
            uniq.append(a)
    return uniq


def classify_recipient(email: str, own_domains: set[str], ctx: PolicyContext) -> tuple[str, str]:
    rdom = registered_domain(email.split("@")[-1])
    if rdom and rdom in own_domains:
        return "internal", f"{email} is internal"
    if rdom and ctx.is_known_domain(rdom):
        return "known", f"{rdom} is a known relationship"
    return "external", f"{email} is external ({rdom or 'unknown domain'}) — not internal or a known relationship"


def risk_tier(d: ActionDescriptor, *, recognised: bool = True) -> str:
    if d.risk:
        return d.risk
    action_id = f"{d.system}_{d.verb}" + (f"_{d.target}" if d.target else "")
    return risk_for(d.verb, recognised=recognised, action_id=action_id)


def r0_org_rule(d: ActionDescriptor, ctx: PolicyContext) -> RuleOutcome:
    rule = (ctx.org_rule(d) or "allowed").lower()
    if rule == "blocked":
        return RuleOutcome("R0", "refuse", f"'{d.qualified_name}' is blocked by your organisation's policy")
    if rule == "approval_required":
        return RuleOutcome("R0", "ask", "Your organisation requires approval for this action")
    return RuleOutcome("R0")


def r1_owner(d: ActionDescriptor, ctx: PolicyContext) -> RuleOutcome:
    if d.owner and d.actor and d.owner != d.actor:
        return RuleOutcome("R1", None, f"Runs on {d.owner}'s connection on behalf of {d.actor}")
    return RuleOutcome("R1")


def r2_target(d: ActionDescriptor, ctx: PolicyContext) -> RuleOutcome:
    if not d.is_write:
        return RuleOutcome("R2")
    own = set(ctx.internal_domains)
    for cand in (ctx.org_domain(), d.actor.split("@")[-1] if d.actor and "@" in d.actor else None):
        if cand:
            own.add(registered_domain(cand))
    emails = addresses(d.params, d.target)
    if not emails:
        return RuleOutcome("R2", target_class="none")
    worst, reasons = "none", []
    for e in emails:
        kind, why = classify_recipient(e, own, ctx)
        reasons.append(why)
        if _CLASS_RANK[kind] > _CLASS_RANK[worst]:
            worst = kind
    return RuleOutcome("R2", None, "; ".join(reasons), target_class=worst)


def r3_placeholders(d: ActionDescriptor, ctx: PolicyContext) -> RuleOutcome:
    if not d.is_write:
        return RuleOutcome("R3")
    for k, v in d.params.items():
        if isinstance(v, str) and _PLACEHOLDER.search(v):
            found = _PLACEHOLDER.findall(v)[:2]
            msg = f"'{k}' has unfilled placeholder(s) {found} — fill before it leaves"
            return RuleOutcome("R3", "ask", msg, hold=True)
    return RuleOutcome("R3")


def r4_risk(d: ActionDescriptor, tier: str) -> RuleOutcome:
    if tier in ("low", "medium"):
        return RuleOutcome("R4", "act", f"{RISK_LABEL[tier]} risk — no confirmation needed")
    return RuleOutcome("R4", "ask", f"{RISK_LABEL[tier]} risk → requires explicit confirmation")
