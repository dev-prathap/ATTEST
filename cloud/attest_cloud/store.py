"""PendingStore-compatible view over the cloud confirm table, so the SDK's Slack notifier and interaction
handler work unchanged on the server."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from attest.descriptor import ActionDescriptor
from attest.gate import ConfirmDecision, ConfirmRequest
from attest_cloud.db import ConfirmRow


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


class DbStore:
    def __init__(self, s: Session, org_id: str | None):
        self.s, self.org_id = s, org_id

    def _q(self, ref: str):
        q = select(ConfirmRow).where(or_(ConfirmRow.id == ref, ConfirmRow.resume_token == ref))
        if self.org_id:
            q = q.where(ConfirmRow.org_id == self.org_id)
        return q

    def _expire(self) -> None:
        now = _now()
        q = select(ConfirmRow).where(ConfirmRow.status == "pending", ConfirmRow.expires_at.is_not(None))
        if self.org_id:
            q = q.where(ConfirmRow.org_id == self.org_id)
        for r in self.s.scalars(q):
            if _aware(r.expires_at) and _aware(r.expires_at) < now:
                r.status, r.decided_at = "expired", now
        self.s.flush()

    def create(self, request: ConfirmRequest, *, ttl_s: float | None = None, meta: dict | None = None) -> str:
        from datetime import timedelta
        row = ConfirmRow(id=request.id, org_id=self.org_id, resume_token=request.resume_token,
                         action_id=request.action_id, channel=request.channel,
                         descriptor=request.descriptor.model_dump(mode="json"), reasons=request.reasons,
                         risk_tier=request.risk_tier, approvers=request.approvers, hold=request.hold,
                         approver_members=list(request.approver_members), meta=meta or {},
                         requested_at=request.requested_at,
                         expires_at=(_now() + timedelta(seconds=ttl_s)) if ttl_s else None)
        self.s.add(row)
        self.s.flush()
        return request.resume_token

    def get(self, ref: str) -> dict[str, Any] | None:
        self._expire()
        r = self.s.scalar(self._q(ref))
        return self.row(r) if r else None

    def decide(self, ref: str, decision: ConfirmDecision) -> bool:
        r = self.s.scalar(self._q(ref).where(ConfirmRow.status == "pending"))
        if r is None:
            return False
        r.status, r.approver, r.edits, r.note = decision.status, decision.approver, decision.edits, decision.note
        r.decided_at, r.channel = decision.decided_at, decision.channel or r.channel
        self.s.flush()
        return True

    def set_meta(self, ref: str, **meta: Any) -> None:
        r = self.s.scalar(self._q(ref))
        if r is not None:
            r.meta = {**(r.meta or {}), **meta}
            self.s.flush()

    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        self._expire()
        q = select(ConfirmRow).where(ConfirmRow.status == "pending").order_by(ConfirmRow.requested_at).limit(limit)
        if self.org_id:
            q = q.where(ConfirmRow.org_id == self.org_id)
        return [self.row(r) for r in self.s.scalars(q)]

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        q = select(ConfirmRow).order_by(ConfirmRow.requested_at.desc()).limit(limit)
        if self.org_id:
            q = q.where(ConfirmRow.org_id == self.org_id)
        return [self.row(r) for r in self.s.scalars(q)]

    def find_pending(self, qualified_name: str, params_hash: str) -> dict[str, Any] | None:
        for row in self.pending():
            d = row["descriptor"]
            name = f"{d.get('system')}.{d.get('verb')}" + (f":{d['target']}" if d.get("target") else "")
            if name == qualified_name and d.get("params_hash") == params_hash:
                return row
        return None

    def request(self, ref: str) -> ConfirmRequest | None:
        row = self.get(ref)
        if row is None:
            return None
        return ConfirmRequest(action_id=row["action_id"], descriptor=ActionDescriptor.model_validate(row["descriptor"]),
                              reasons=row["reasons"], risk_tier=row["risk_tier"], approvers=row["approvers"],
                              hold=row["hold"], approver_members=row.get("approver_members") or [],
                              channel=row["channel"] or "cloud", id=row["id"],
                              resume_token=row["resume_token"],
                              requested_at=datetime.fromisoformat(row["requested_at"]))

    def decision(self, ref: str) -> ConfirmDecision | None:
        row = self.get(ref)
        if row is None:
            return None
        if row["status"] == "pending":
            return ConfirmDecision("pending", channel=row["channel"] or "cloud")
        return ConfirmDecision(row["status"], row["approver"], row["edits"], row["note"],
                              channel=row["channel"] or "cloud",
                              decided_at=datetime.fromisoformat(row["decided_at"]) if row["decided_at"] else _now())

    @staticmethod
    def row(r: ConfirmRow) -> dict[str, Any]:
        return {"id": r.id, "org_id": r.org_id, "resume_token": r.resume_token, "action_id": r.action_id,
                "status": r.status, "channel": r.channel, "descriptor": r.descriptor, "reasons": r.reasons,
                "risk_tier": r.risk_tier, "approvers": r.approvers, "approver_members": r.approver_members or [],
                "hold": r.hold, "approver": r.approver,
                "edits": r.edits, "note": r.note, "meta": r.meta or {},
                "requested_at": _aware(r.requested_at).isoformat() if r.requested_at else None,
                "decided_at": _aware(r.decided_at).isoformat() if r.decided_at else None,
                "expires_at": _aware(r.expires_at).isoformat() if r.expires_at else None}
