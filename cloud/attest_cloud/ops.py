"""Ops (P2.8): per-key rate limiting, error tracking hook, request logging.

  ATTEST_RATE_LIMIT      requests per minute per API key (default 600; 0 disables)
  ATTEST_RATE_BURST      burst size (default = limit / 6)
  SENTRY_DSN             when set and sentry_sdk is importable, exceptions are reported (optional dependency)
"""
from __future__ import annotations

import logging
import os
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("attest.cloud")


class TokenBucket:
    def __init__(self, rate_per_min: float, burst: float):
        self.rate, self.burst = rate_per_min / 60.0, burst
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> tuple[bool, float]:
        now = time.monotonic() if now is None else now
        with self._lock:
            tokens, last = self._buckets.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens >= 1:
                self._buckets[key] = (tokens - 1, now)
                return True, 0.0
            self._buckets[key] = (tokens, now)
            return False, (1 - tokens) / self.rate if self.rate else 60.0

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


def install(app: FastAPI, *, rate_per_min: float | None = None, burst: float | None = None) -> TokenBucket | None:
    limit = float(os.environ.get("ATTEST_RATE_LIMIT", "600")) if rate_per_min is None else rate_per_min
    if limit <= 0:
        return None
    default_burst = float(os.environ.get("ATTEST_RATE_BURST", str(max(10, limit / 6))))
    bucket = TokenBucket(limit, burst if burst is not None else default_burst)
    app.state.rate_bucket = bucket

    @app.middleware("http")
    async def _rate_limit(request: Request, call_next):
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            key = auth.split(" ", 1)[1][:24]
        else:
            key = request.client.host if request.client else "anon"
        ok, retry = app.state.rate_bucket.allow(key)
        if not ok:
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429,
                                headers={"Retry-After": str(int(retry) + 1)})
        return await call_next(request)

    return bucket


def install_error_tracking(app: FastAPI) -> bool:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return False
    try:
        import sentry_sdk  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover - optional
        log.warning("SENTRY_DSN set but sentry_sdk is not installed")
        return False
    sentry_sdk.init(dsn=dsn, traces_sample_rate=float(os.environ.get("SENTRY_TRACES", "0")), send_default_pii=False)
    return True
