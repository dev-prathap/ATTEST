"""Opt-in SDK telemetry (P2.8). Off unless ATTEST_TELEMETRY=1. Sends counts only — never descriptors, params,
targets, actors, or hashes: {sdk_version, python, counts by decision / level / system, entry_point}."""
from __future__ import annotations

import json
import os
import platform
import threading
import urllib.request
from collections import Counter
from typing import Any

ENDPOINT = os.environ.get("ATTEST_TELEMETRY_URL", "https://telemetry.attest.dev/v1/sdk")


class Telemetry:
    def __init__(self, enabled: bool | None = None, endpoint: str | None = None, *, post: Any = None):
        env_on = os.environ.get("ATTEST_TELEMETRY", "").lower() in ("1", "true", "yes")
        self.enabled = env_on if enabled is None else enabled
        self.endpoint, self._post = endpoint or ENDPOINT, post
        self.counts: Counter[str] = Counter()
        self._lock = threading.RLock()  # record() flushes while holding it

    def record(self, *, decision: str, level: str, system: str, entry_point: str = "decorator") -> None:
        if not self.enabled:
            return
        with self._lock:
            self.counts[f"decision:{decision}"] += 1
            self.counts[f"level:{level}"] += 1
            self.counts[f"system:{system if system in _KNOWN else 'other'}"] += 1
            self.counts[f"entry:{entry_point}"] += 1
            self.counts["actions"] += 1
            if self.counts["actions"] % 50 == 0:
                self.flush()

    def payload(self) -> dict[str, Any]:
        return {"sdk_version": "0.1.0", "python": platform.python_version(), "os": platform.system(),
                "counts": dict(self.counts)}

    def flush(self) -> bool:
        if not self.enabled or not self.counts:
            return False
        body = json.dumps(self.payload()).encode()
        try:
            if self._post is not None:
                self._post(self.endpoint, body)
            else:  # pragma: no cover - network
                req = urllib.request.Request(self.endpoint, data=body, method="POST",
                                             headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5).close()  # noqa: S310
        except Exception:  # noqa: BLE001 - telemetry must never break the agent
            return False
        with self._lock:
            self.counts.clear()
        return True


_KNOWN = {"gmail", "slack", "hubspot", "calendar", "drive", "docs", "sheets", "notion", "linear", "outlook", "teams",
          "unknown"}
