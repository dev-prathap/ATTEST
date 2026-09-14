"""Per-org hash chain over cloud ledger rows. Same construction as the SDK's local chain
(`attest.ledger.hashchain`), so an exported cloud ledger verifies with the same code."""
from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from attest.ledger import checkpoints as cps
from attest.ledger import hashchain
from attest_cloud.db import CheckpointRow, LedgerRow, Org


def signing_key() -> str | None:
    return os.environ.get("ATTEST_SIGNING_KEY")


def append(s: Session, org_id: str, payload: dict[str, Any], *, entry_id: str, client_seq: int | None,
           client_hash: str | None) -> tuple[LedgerRow, bool]:
    """Caller holds the org chain lock. Idempotent on (org, entry_id). Returns (row, created)."""
    existing = s.scalar(select(LedgerRow).where(LedgerRow.org_id == org_id, LedgerRow.entry_id == entry_id))
    if existing is not None:
        return existing, False
    s.execute(select(Org.id).where(Org.id == org_id).with_for_update())  # row lock on Postgres; no-op on SQLite
    tail = s.scalar(select(LedgerRow).where(LedgerRow.org_id == org_id).order_by(LedgerRow.seq.desc()).limit(1))
    seq = (tail.seq + 1) if tail else 1
    prev = tail.hash if tail else hashchain.GENESIS
    ph = hashchain.payload_hash(payload)
    h = hashchain.entry_hash(prev, seq, ph)
    d = payload.get("descriptor") or {}
    row = LedgerRow(org_id=org_id, seq=seq, entry_id=entry_id, action_id=payload.get("action_id", ""),
                    run_id=payload.get("run_id"), agent=payload.get("agent"), actor=payload.get("actor"),
                    system=d.get("system"), verb=d.get("verb"), decision=payload.get("decision", ""),
                    level=(payload.get("verification") or {}).get("level", "attested-only"), payload=payload,
                    payload_hash=ph, prev_hash=prev, hash=h, client_seq=client_seq, client_hash=client_hash)
    s.add(row)
    s.flush()
    return row, True


def verify(s: Session, org_id: str) -> hashchain.ChainReport:
    rows = s.scalars(select(LedgerRow).where(LedgerRow.org_id == org_id).order_by(LedgerRow.seq)).all()
    anchor = None
    if rows and rows[0].seq > 1:
        cp = s.scalar(select(CheckpointRow).where(CheckpointRow.org_id == org_id, CheckpointRow.seq == rows[0].seq - 1))
        if cp is None:
            problem = f"rows before seq {rows[0].seq} are missing and no checkpoint anchors the chain"
            return hashchain.ChainReport(False, 0, rows[0].seq, [problem])
        anchor = (cp.seq, cp.hash)
    return hashchain.verify([{"seq": r.seq, "prev_hash": r.prev_hash, "payload_hash": r.payload_hash, "hash": r.hash,
                              "payload": r.payload} for r in rows], anchor=anchor)


def checkpoint(s: Session, org_id: str, org_slug: str, *, reason: str = "manual") -> CheckpointRow | None:
    tail = s.scalar(select(LedgerRow).where(LedgerRow.org_id == org_id).order_by(LedgerRow.seq.desc()).limit(1))
    if tail is None:
        return None
    cp = cps.sign(tail.seq, tail.hash, key=signing_key(), scope=f"org:{org_slug}")
    existing = s.scalar(select(CheckpointRow).where(CheckpointRow.org_id == org_id, CheckpointRow.seq == cp.seq))
    if existing:
        return existing
    row = CheckpointRow(org_id=org_id, seq=cp.seq, hash=cp.hash, signed_at=cp.signed_at, scope=cp.scope,
                        signature=cp.signature, key_id=cp.key_id, reason=reason)
    s.add(row)
    s.flush()
    return row


def checkpoints(s: Session, org_id: str) -> list[dict[str, Any]]:
    rows = s.scalars(select(CheckpointRow).where(CheckpointRow.org_id == org_id).order_by(CheckpointRow.seq)).all()
    return [{"seq": r.seq, "hash": r.hash, "signed_at": r.signed_at, "scope": r.scope, "signature": r.signature,
             "key_id": r.key_id, "reason": r.reason} for r in rows]


def prune(s: Session, org_id: str, org_slug: str, *, before_seq: int) -> int:
    """Retention: delete rows with seq < before_seq (never the head), anchoring the chain with a checkpoint."""
    head = s.scalar(select(LedgerRow).where(LedgerRow.org_id == org_id).order_by(LedgerRow.seq.desc()).limit(1))
    if head is None:
        return 0
    before_seq = min(before_seq, head.seq)
    last = s.scalar(select(LedgerRow).where(LedgerRow.org_id == org_id, LedgerRow.seq < before_seq)
                    .order_by(LedgerRow.seq.desc()).limit(1))
    if last is None:
        return 0
    cp = cps.sign(last.seq, last.hash, key=signing_key(), scope=f"org:{org_slug}")
    if not s.scalar(select(CheckpointRow).where(CheckpointRow.org_id == org_id, CheckpointRow.seq == cp.seq)):
        s.add(CheckpointRow(org_id=org_id, seq=cp.seq, hash=cp.hash, signed_at=cp.signed_at, scope=cp.scope,
                            signature=cp.signature, key_id=cp.key_id, reason="retention"))
    victims = s.scalars(select(LedgerRow).where(LedgerRow.org_id == org_id, LedgerRow.seq < before_seq)).all()
    for v in victims:
        s.delete(v)
    s.flush()
    return len(victims)
