"""Optional Ed25519 signing for checkpoints and manifests (P3.5). HMAC stays the default (no dependency);
with `pip install "attest[signing]"` (cryptography) you get public-key signatures anyone can verify offline."""
from __future__ import annotations

import base64
from typing import Any


def available() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def generate_keypair() -> tuple[str, str]:
    """→ (private_key_b64, public_key_b64), raw 32-byte keys."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    priv = Ed25519PrivateKey.generate()
    pb = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    ub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(pb).decode(), base64.b64encode(ub).decode()


def sign(message: bytes, private_key_b64: str) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64))
    return "ed25519=" + base64.b64encode(priv.sign(message)).decode()


def verify(message: bytes, signature: str, public_key_b64: str) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    if not signature.startswith("ed25519="):
        return False
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64)).verify(base64.b64decode(signature[8:]), message)
        return True
    except (InvalidSignature, ValueError):
        return False


def sign_checkpoint(cp: Any, private_key_b64: str) -> Any:
    from attest.ledger.checkpoints import _message
    cp.signature = sign(_message(cp.scope, cp.seq, cp.hash, cp.signed_at), private_key_b64)
    cp.key_id = "ed25519"
    return cp


def verify_checkpoint(cp: Any, public_key_b64: str) -> bool:
    from attest.ledger.checkpoints import _message
    d = cp.to_dict() if hasattr(cp, "to_dict") else cp
    return bool(d.get("signature")) and verify(_message(d["scope"], int(d["seq"]), d["hash"], d["signed_at"]), d["signature"], public_key_b64)
