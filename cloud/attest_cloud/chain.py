"""Per-org hash chain over cloud ledger rows. Same construction as the SDK's local chain
(`attest.ledger.hashchain`), so an exported cloud ledger verifies with the same code."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from attest.ledger import hashchain
from attest_cloud.db import LedgerRow, Org


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
    return hashchain.verify([{"seq": r.seq, "prev_hash": r.prev_hash, "payload_hash": r.payload_hash, "hash": r.hash,
                              "payload": r.payload} for r in rows])
