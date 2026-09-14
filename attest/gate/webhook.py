"""Webhook notifier: POST the confirm request to the customer's own UI/endpoint. They answer by calling
`POST /confirm/{id}` on the Attest server (see attest.server) or `store.decide(...)` directly."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.request
from typing import Any

from attest.gate import ConfirmRequest


class WebhookNotifier:
    name = "webhook"

    def __init__(self, url: str, *, secret: str | None = None, confirm_url: str | None = None,
                 headers: dict[str, str] | None = None, timeout_s: float = 10.0, post: Any = None):
        self.url, self.secret, self.confirm_url = url, secret, confirm_url
        self.headers, self.timeout_s, self._post = headers or {}, timeout_s, post

    def payload(self, request: ConfirmRequest) -> dict[str, Any]:
        body = {"type": "attest.confirm_request", **request.to_dict()}
        if self.confirm_url:
            body["confirm_url"] = f"{self.confirm_url.rstrip('/')}/confirm/{request.id}"
        return body

    def notify(self, request: ConfirmRequest, store: Any) -> None:
        body = json.dumps(self.payload(request), default=str).encode()
        headers = {"Content-Type": "application/json", **self.headers}
        if self.secret:
            ts = str(int(time.time()))
            sig = hmac.new(self.secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
            headers["X-Attest-Timestamp"], headers["X-Attest-Signature"] = ts, f"v1={sig}"
        if self._post is not None:
            self._post(self.url, body, headers)
            return
        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout_s):  # noqa: S310 - customer-supplied URL
            pass
        store.set_meta(request.id, webhook_url=self.url)


def verify_signature(secret: str, timestamp: str, body: bytes, signature: str, *, max_age_s: int = 300) -> bool:
    """For customers verifying our webhook: `X-Attest-Signature: v1=<hmac_sha256(secret, "<ts>." + body)>`."""
    try:
        if abs(time.time() - int(timestamp)) > max_age_s:
            return False
    except ValueError:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"v1={expected}", signature)
