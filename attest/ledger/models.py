"""What one ledger entry records (doc 02 §4, doc 04 data model). Params and results are stored as
hashes plus an allow-listed preview; full payloads never enter the ledger by default."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from attest.descriptor import ActionDescriptor, new_id, short_hash

VerificationLevel = str  # verified | verified-custom | acknowledged | attested-only | unverified

PREVIEW_KEYS = ("to", "cc", "recipient", "recipients", "channel", "channel_id", "id", "name", "title", "subject",
                "email", "url", "path", "key", "ts", "message_id", "thread_id", "resource_name", "status", "ok",
                "amount", "currency", "role", "labels", "dealname", "properties")
_PREVIEW_MAX = 120


def preview(obj: Any, keys: tuple[str, ...] = PREVIEW_KEYS) -> dict[str, Any] | str | None:
    """Small, non-content view of params or a result: allow-listed keys, values truncated, nothing nested deep."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k in keys or k.endswith("_id") or k.endswith("Id"):
                if isinstance(v, (dict, list)):
                    v = short_hash(v) if len(str(v)) > _PREVIEW_MAX else v
                elif isinstance(v, str) and len(v) > _PREVIEW_MAX:
                    v = v[:_PREVIEW_MAX] + "…"
                out[k] = v
        return out
    s = str(obj)
    return s[:_PREVIEW_MAX] + ("…" if len(s) > _PREVIEW_MAX else "")


class ConfirmRecord(BaseModel):
    status: str  # not_required | approved | rejected | edited | pending | expired
    channel: str | None = None
    approver: str | None = None
    requested_at: datetime | None = None
    decided_at: datetime | None = None
    edits: dict[str, Any] | None = None
    note: str | None = None


class ExecutionRecord(BaseModel):
    status: str  # done | failed | skipped
    result_hash: str | None = None
    result_preview: Any = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None


class VerificationRecord(BaseModel):
    level: VerificationLevel = "attested-only"
    method: str | None = None  # ack | custom | recipe:<name> | convention | none
    matched: bool | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    checked_at: datetime | None = None


class LedgerEntry(BaseModel):
    """The payload that gets hashed. `seq`, `prev_hash`, `hash` are assigned by the ledger on append."""

    id: str = Field(default_factory=lambda: new_id("led"))
    action_id: str
    run_id: str | None = None
    agent: str | None = None
    actor: str | None = None
    descriptor: dict[str, Any]
    params_hash: str
    params_preview: Any = None
    decision: str
    risk_tier: str
    reasons: list[str] = Field(default_factory=list)
    rules_fired: list[str] = Field(default_factory=list)
    target_class: str = "none"
    confirm: ConfirmRecord = Field(default_factory=lambda: ConfirmRecord(status="not_required"))
    execution: ExecutionRecord | None = None
    verification: VerificationRecord = Field(default_factory=VerificationRecord)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sdk: str = "attest-python/0.1.0"

    seq: int | None = None
    prev_hash: str | None = None
    payload_hash: str | None = None
    hash: str | None = None

    def payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"seq", "prev_hash", "payload_hash", "hash"})

    @classmethod
    def from_descriptor(cls, d: ActionDescriptor, *, decision: str, risk_tier: str, **kw: Any) -> LedgerEntry:
        return cls(action_id=d.id, run_id=d.run_id, agent=d.agent, actor=d.actor, descriptor=d.to_ledger(),
                   params_hash=d.params_hash, params_preview=preview(d.params), decision=decision,
                   risk_tier=risk_tier, **kw)
