"""Hash chain over ledger entries. Each entry's hash covers its canonical payload and the previous
entry's hash, so editing, deleting or reordering any row breaks every hash after it."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from attest.descriptor import canonical_json

GENESIS = "0" * 64


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def entry_hash(prev_hash: str, seq: int, payload_hash_: str) -> str:
    return hashlib.sha256(f"{prev_hash}|{seq}|{payload_hash_}".encode()).hexdigest()


@dataclass
class ChainReport:
    ok: bool
    checked: int
    broken_at: int | None = None  # seq of the first bad entry
    problems: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


def verify(rows: list[dict[str, Any]], *, anchor: tuple[int, str] | None = None) -> ChainReport:
    """`rows` in seq order, each with seq, prev_hash, payload_hash, hash, payload (dict).
    `anchor=(seq, hash)` is a checkpoint: verification starts at seq+1 with prev=hash (rows before it were pruned)."""
    prev, expected_seq = GENESIS, 1
    if anchor is not None:
        prev, expected_seq = anchor[1], anchor[0] + 1
        rows = [r for r in rows if r["seq"] > anchor[0]]
    for row in rows:
        seq = row["seq"]
        if seq != expected_seq:
            return ChainReport(False, seq - 1, seq, [f"seq gap: expected {expected_seq}, found {seq}"])
        if row["prev_hash"] != prev:
            return ChainReport(False, seq - 1, seq, [f"prev_hash mismatch at seq {seq}"])
        ph = payload_hash(row["payload"])
        if ph != row["payload_hash"]:
            return ChainReport(False, seq - 1, seq, [f"payload altered at seq {seq}"])
        h = entry_hash(prev, seq, ph)
        if h != row["hash"]:
            return ChainReport(False, seq - 1, seq, [f"hash mismatch at seq {seq}"])
        prev, expected_seq = h, seq + 1
    return ChainReport(True, expected_seq - 1)
