"""Signed checkpoints + retention for hash-chained ledgers.

A checkpoint pins (seq, hash) at a point in time with an HMAC signature. Two uses:
  * proof of integrity at that moment (export it, publish it, anchor it externally later);
  * retention: rows *before* a checkpoint can be pruned and the chain still verifies from the checkpoint on.

Signing key: HMAC-SHA256 over "attest-checkpoint|<scope>|<seq>|<hash>|<signed_at>". Locally the key comes from
`ATTEST_LEDGER_KEY` (unsigned checkpoints are allowed — `signature` is then null); the cloud signs with its
server key per org. External anchoring (timestamping) is Phase 3.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class Checkpoint:
    seq: int
    hash: str
    signed_at: str
    scope: str = "local"
    signature: str | None = None
    key_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "hash": self.hash, "signed_at": self.signed_at, "scope": self.scope,
                "signature": self.signature, "key_id": self.key_id}


def _message(scope: str, seq: int, hash_: str, signed_at: str) -> bytes:
    return f"attest-checkpoint|{scope}|{seq}|{hash_}|{signed_at}".encode()


def key_id(key: str | bytes) -> str:
    k = key.encode() if isinstance(key, str) else key
    return hashlib.sha256(k).hexdigest()[:12]


def sign(seq: int, hash_: str, *, key: str | bytes | None, scope: str = "local",
         signed_at: str | None = None) -> Checkpoint:
    signed_at = signed_at or datetime.now(UTC).isoformat()
    cp = Checkpoint(seq, hash_, signed_at, scope)
    if key:
        k = key.encode() if isinstance(key, str) else key
        cp.signature = "v1=" + hmac.new(k, _message(scope, seq, hash_, signed_at), hashlib.sha256).hexdigest()
        cp.key_id = key_id(k)
    return cp


def verify_signature(cp: Checkpoint | dict[str, Any], key: str | bytes) -> bool:
    d = cp.to_dict() if isinstance(cp, Checkpoint) else cp
    if not d.get("signature"):
        return False
    k = key.encode() if isinstance(key, str) else key
    expected = "v1=" + hmac.new(k, _message(d.get("scope", "local"), int(d["seq"]), d["hash"], d["signed_at"]),
                                hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, d["signature"])


def sign_manifest(payload: dict[str, Any], *, key: str | bytes | None, scope: str = "local") -> dict[str, Any]:
    """Detached signature over a canonical JSON manifest (exports)."""
    from attest.descriptor import canonical_json
    digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    out = {"digest": digest, "algorithm": "sha256", "signature": None, "key_id": None, "scope": scope}
    if key:
        k = key.encode() if isinstance(key, str) else key
        out["signature"] = "v1=" + hmac.new(k, f"attest-manifest|{scope}|{digest}".encode(), hashlib.sha256).hexdigest()
        out["key_id"] = key_id(k)
    return out
