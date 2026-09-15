"""Signed one-click decision links for channels that cannot call back (email, Teams webhooks)."""
from __future__ import annotations

import hashlib
import hmac
import time


def sign_link(secret: str, request_id: str, status: str, expires: int) -> str:
    return hmac.new(secret.encode(), f"{request_id}|{status}|{expires}".encode(), hashlib.sha256).hexdigest()[:32]


def decision_links(inbox_url: str, request_id: str, secret: str, ttl_s: int = 86400) -> tuple[str, str]:
    exp = int(time.time()) + ttl_s
    base = inbox_url.rstrip("/")
    return (f"{base}/decide/{request_id}/approved?exp={exp}&sig={sign_link(secret, request_id, 'approved', exp)}",
            f"{base}/decide/{request_id}/rejected?exp={exp}&sig={sign_link(secret, request_id, 'rejected', exp)}")


def verify_link(secret: str, request_id: str, status: str, exp: int, sig: str) -> bool:
    if exp < time.time():
        return False
    return hmac.compare_digest(sign_link(secret, request_id, status, exp), sig)
