"""Evidence exports (doc 02 §4, P2.3).

  ietf_records()   — IETF draft-sharif-agent-audit-trail records (JSONL): record_id, timestamp, agent_id,
                     agent_version, session_id, action_type, action_detail, outcome, trust_level, parent_record_id,
                     prev_hash (SHA-256 of the canonical previous record), record_phase, plus optional fields
                     (human_override, risk_score, input_hash, output_hash, latency_ms, deny_reasons, signature).
  eu_ai_act_pack() — an event-log pack for Article 12-style record-keeping: system identification, period,
                     per-event records with human-oversight and outcome-verification fields, integrity section
                     (chain head, checkpoints, signed manifest), and a field map. Engineering aid, not legal advice.

Trust levels: attested-only ⇒ L0 · acknowledged ⇒ L1 · verified-custom ⇒ L2 · verified ⇒ L3 · unverified ⇒ L0
(with outcome "failure" and a deny_reason naming the contradiction). L4 is reserved for externally anchored records.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from attest.descriptor import canonical_json
from attest.ledger.checkpoints import sign_manifest
from attest.ledger.models import LedgerEntry

_NS = uuid.UUID("6f1b4b1e-2b9e-4f3c-9a1d-attest000001".replace("attest000001", "a77e57000001"))
TRUST = {"attested-only": "L0", "acknowledged": "L1", "verified-custom": "L2", "verified": "L3", "unverified": "L0"}
SDK_VERSION = "0.1.0"


def _uuid(value: str | None) -> str | None:
    return str(uuid.uuid5(_NS, value)) if value else None


def _outcome(e: LedgerEntry) -> str:
    c, x, v = e.confirm.status, e.execution, e.verification.level
    if e.decision == "refuse" or c == "rejected":
        return "denied"
    if c == "expired":
        return "timeout"
    if c == "pending":
        return "escalated"
    if x is None:
        return "denied"
    if x.status == "failed" or v == "unverified":
        return "failure"
    return "success"


def _ts(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def ietf_record(e: LedgerEntry, prev_record: dict[str, Any] | None) -> dict[str, Any]:
    d = e.descriptor
    deny = []
    if e.decision == "refuse":
        deny = list(e.reasons)
    elif e.confirm.status in ("rejected", "expired"):
        deny = [e.confirm.note or f"confirmation {e.confirm.status}"]
    elif e.verification.level == "unverified":
        deny = ["read-back contradicted the claimed result: " + ", ".join(e.verification.evidence.get("failed") or [])]
    rec: dict[str, Any] = {
        "record_id": _uuid(e.id),
        "timestamp": _ts(e.created_at),
        "agent_id": f"urn:attest:agent:{e.agent or 'unknown'}",
        "agent_version": SDK_VERSION,
        "session_id": _uuid(e.run_id or e.action_id),
        "action_type": "tool_call",
        "action_detail": {
            "tool_name": d.get("extra", {}).get("tool_name") or f"{d.get('system')}.{d.get('verb')}",
            "system": d.get("system"), "verb": d.get("verb"), "target": d.get("target"),
            "target_class": e.target_class, "actor": e.actor, "action_id": e.action_id,
            "decision": e.decision, "reasons": e.reasons, "rules_fired": e.rules_fired,
            "params_preview": e.params_preview,
            "execution": e.execution.model_dump(mode="json") if e.execution else None,
            "verification": e.verification.model_dump(mode="json"),
            "attest_seq": e.seq, "attest_hash": e.hash,
        },
        "outcome": _outcome(e),
        "trust_level": TRUST.get(e.verification.level, "L0"),
        "parent_record_id": prev_record["record_id"] if prev_record else None,
        "prev_hash": hashlib.sha256(canonical_json(prev_record).encode()).hexdigest() if prev_record else None,
        "record_phase": "post_execution" if e.execution else "pre_execution",
        "human_override": ({"status": e.confirm.status, "approver": e.confirm.approver, "channel": e.confirm.channel,
                            "decided_at": _ts(e.confirm.decided_at), "edits": e.confirm.edits}
                           if e.confirm.status != "not_required" else None),
        "risk_score": {"low": 0.25, "medium": 0.5, "high": 0.75, "very_high": 1.0}.get(e.risk_tier),
        "input_hash": e.params_hash,
        "output_hash": e.execution.result_hash if e.execution else None,
        "latency_ms": e.execution.duration_ms if e.execution else None,
        "deny_reasons": deny or None,
        "recording_component": f"attest-python/{SDK_VERSION}",
        "signature": None,
    }
    return rec


def ietf_records(entries: list[LedgerEntry]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    prev = None
    for e in sorted(entries, key=lambda x: x.seq or 0):
        rec = ietf_record(e, prev)
        out.append(rec)
        prev = rec
    return out


def ietf_jsonl(entries: list[LedgerEntry]) -> str:
    lines = [json.dumps(r, sort_keys=True, default=str) for r in ietf_records(entries)]
    return "\n".join(lines) + ("\n" if lines else "")


FIELD_MAP = {
    "system_identification": "agent name + SDK version per event; org / deployment in `system`",
    "period_of_use": "`period.from` / `period.to` — first and last event timestamps in the pack",
    "reference_database": "`events[].action.system` + `target` — the system of record touched",
    "input_data": "`events[].input_hash` (SHA-256 of canonical params) + allow-listed `input_preview`; "
                  "raw inputs are never logged",
    "human_oversight": "`events[].human_oversight` — decision, approver identity, channel, time, edits",
    "outcome": "`events[].outcome` + `events[].verification` — execution status and read-back level with evidence",
    "identification_of_persons": "`events[].actor` (on whose authority) and `human_oversight.approver`",
    "integrity": "`integrity.chain` — per-event hash chain, checkpoints, signed manifest",
}


def eu_ai_act_pack(entries: list[LedgerEntry], *, system: dict[str, Any] | None = None,
                   checkpoints: list[dict[str, Any]] | None = None, chain: dict[str, Any] | None = None,
                   signing_key: str | bytes | None = None, scope: str = "local") -> dict[str, Any]:
    entries = sorted(entries, key=lambda x: x.seq or 0)
    events = []
    for e in entries:
        d = e.descriptor
        events.append({
            "event_id": e.id, "seq": e.seq, "timestamp": _ts(e.created_at), "agent": e.agent, "actor": e.actor,
            "run_id": e.run_id,
            "action": {"system": d.get("system"), "verb": d.get("verb"), "target": d.get("target"),
                       "target_class": e.target_class, "source": d.get("source")},
            "input_hash": e.params_hash, "input_preview": e.params_preview,
            "decision": {"decision": e.decision, "risk_tier": e.risk_tier, "reasons": e.reasons,
                         "rules_fired": e.rules_fired},
            "human_oversight": e.confirm.model_dump(mode="json"),
            "outcome": (e.execution.model_dump(mode="json") if e.execution else {"status": "not_executed"}),
            "verification": e.verification.model_dump(mode="json"),
            "integrity": {"hash": e.hash, "prev_hash": e.prev_hash},
        })
    pack: dict[str, Any] = {
        "format": "attest-eu-ai-act-event-log/1",
        "generated_at": datetime.now(UTC).isoformat(),
        "notice": "Engineering record of automatic event logging. Not legal advice; obligations depend on the "
                  "system's classification under the EU AI Act.",
        "system": {"name": "attest", "sdk_version": SDK_VERSION, **(system or {})},
        "period": {"from": _ts(entries[0].created_at) if entries else None,
                   "to": _ts(entries[-1].created_at) if entries else None, "events": len(events)},
        "summary": {
            "by_level": _count(e.verification.level for e in entries),
            "by_decision": _count(e.decision for e in entries),
            "by_outcome": _count(_outcome(e) for e in entries),
            "human_decisions": _count(e.confirm.status for e in entries if e.confirm.status != "not_required"),
        },
        "field_map": FIELD_MAP,
        "events": events,
        "integrity": {"chain": chain or {"head": entries[-1].hash if entries else None, "entries": len(entries)},
                      "checkpoints": checkpoints or []},
    }
    pack["manifest"] = sign_manifest({k: v for k, v in pack.items() if k != "manifest"}, key=signing_key, scope=scope)
    return pack


def _count(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return out
