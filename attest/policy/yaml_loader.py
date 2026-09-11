"""Declarative rules (doc 03 §7). Evaluated on the descriptor; first match wins.

policies:
  - match: { verb: [send, share], target: external }
    decision: ask
    approvers: [sales-leads]
    reason: external sends need a human
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from attest.descriptor import ActionDescriptor
from attest.registry.systems import registered_domain

MATCH_KEYS = {"system", "verb", "target", "target_class", "target_domain", "actor", "agent", "risk", "action"}
DECISIONS = {"act", "ask", "refuse"}


@dataclass
class Rule:
    match: dict[str, list[str]]
    decision: str
    approvers: list[str] = field(default_factory=list)
    reason: str | None = None
    name: str | None = None

    def matches(self, d: ActionDescriptor, *, tier: str, target_class: str) -> bool:
        for key, wanted in self.match.items():
            if key == "system":
                have = [d.system]
            elif key == "verb":
                have = [d.verb]
            elif key in ("target", "target_class"):
                have = [target_class]
            elif key == "target_domain":
                have = target_domains(d)
            elif key == "actor":
                have = [d.actor or ""]
            elif key == "agent":
                have = [d.agent or ""]
            elif key == "risk":
                have = [tier]
            elif key == "action":
                have = [d.qualified_name, f"{d.system}.{d.verb}"]
            else:
                return False
            wanted_l = [w.lower() for w in wanted]
            if not any(h.lower() in wanted_l or _glob(h.lower(), wanted_l) for h in have):
                return False
        return True


def _glob(value: str, patterns: list[str]) -> bool:
    from fnmatch import fnmatchcase
    return any("*" in p and fnmatchcase(value, p) for p in patterns)


def target_domains(d: ActionDescriptor) -> list[str]:
    from attest.policy.rules import addresses
    out = {registered_domain(e.split("@")[-1]) for e in addresses(d.params, d.target)}
    if d.target and "@" not in d.target and "." in d.target and "/" not in d.target:
        out.add(registered_domain(d.target))
    return sorted(x for x in out if x)


def _listify(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple, set)):
        return [str(x) for x in v]
    return [str(v)]


def parse_rules(doc: dict[str, Any] | list[Any]) -> list[Rule]:
    items = doc.get("policies", doc.get("rules", [])) if isinstance(doc, dict) else doc
    rules: list[Rule] = []
    for i, item in enumerate(items or []):
        if not isinstance(item, dict):
            raise ValueError(f"policy #{i}: expected a mapping, got {type(item).__name__}")
        match = item.get("match") or {}
        bad = set(match) - MATCH_KEYS
        if bad:
            raise ValueError(f"policy #{i}: unknown match keys {sorted(bad)}; allowed: {sorted(MATCH_KEYS)}")
        decision = str(item.get("decision", "")).lower()
        if decision not in DECISIONS:
            raise ValueError(f"policy #{i}: decision must be one of {sorted(DECISIONS)}, got {decision!r}")
        rules.append(Rule({k: _listify(v) for k, v in match.items()}, decision, _listify(item.get("approvers")),
                          item.get("reason"), item.get("name")))
    return rules


def load_yaml(text: str) -> list[Rule]:
    return parse_rules(yaml.safe_load(text) or {})


def load_file(path: str | Path) -> list[Rule]:
    return load_yaml(Path(path).read_text())


DEFAULT_POLICY_YAML = """\
# Attest default policy — sensible behaviour for any system, by verb and target (doc 03 §7).
policies:
  - name: external-send
    match: { verb: [send, reply, share, upload], target: external }
    decision: ask
    reason: reaches someone outside the organisation
  - name: destructive-or-money
    match: { verb: [delete, pay] }
    decision: ask
  - name: unknown-system-write
    match: { system: unknown, verb: [write, execute, approve] }
    decision: ask
    reason: side effect on an unrecognised system
  - name: reads
    match: { verb: [read, search, get, list] }
    decision: act
"""


def default_rules() -> list[Rule]:
    return load_yaml(DEFAULT_POLICY_YAML)
