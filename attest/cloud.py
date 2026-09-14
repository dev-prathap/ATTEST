"""SDK ⇄ Attest Cloud (P1.4.4): ledger sink, policy sync, cloud-routed confirmations.

    at = Attest.cloud("https://cloud.attest.dev", api_key="atk_…")     # or ATTEST_CLOUD_URL / ATTEST_API_KEY

  * every ledger entry is appended locally (SQLite, hash-chained) and pushed to the cloud; failures queue in a
    local outbox and retry on the next append / `flush()` — the agent never blocks on the cloud
  * the policy YAML is fetched from the cloud at start (`refresh()` later); local/default is the fallback
  * confirmations are created in the cloud, which notifies Slack / webhook with the org's settings; the SDK
    polls (block) or returns a resume token (pending) — the same `StoreGate` as local, over `CloudStore`
No vendor tokens ever reach the cloud; read-back stays in-process (see readers).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from attest.descriptor import ActionDescriptor
from attest.gate import ConfirmDecision, ConfirmRequest
from attest.ledger import LedgerEntry, SqliteLedger
from attest.policy import PolicyContext, PolicyEngine

log = logging.getLogger("attest.cloud")
Transport = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, Any]]


class CloudError(Exception):
    def __init__(self, status: int, detail: Any):
        self.status, self.detail = status, detail
        super().__init__(f"cloud {status}: {detail}")


def _urllib_transport(method: str, url: str, body: bytes | None, headers: dict[str, str]) -> tuple[int, Any]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 - customer-configured cloud URL
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw.decode(errors="replace")


class CloudClient:
    def __init__(self, url: str | None = None, api_key: str | None = None, *, transport: Transport | None = None):
        self.url = (url or os.environ.get("ATTEST_CLOUD_URL") or "").rstrip("/")
        self.api_key = api_key or os.environ.get("ATTEST_API_KEY") or ""
        if not self.url or not self.api_key:
            raise ValueError("Attest Cloud needs url + api_key (or ATTEST_CLOUD_URL / ATTEST_API_KEY)")
        self._send = transport or _urllib_transport

    def request(self, method: str, path: str, body: Any = None, *, params: dict[str, Any] | None = None) -> Any:
        url = self.url + path
        if params:
            from urllib.parse import urlencode
            url += "?" + urlencode({k: v for k, v in params.items() if v is not None})
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body, default=str).encode()
            headers["Content-Type"] = "application/json"
        status, out = self._send(method, url, data, headers)
        if status >= 400:
            raise CloudError(status, (out or {}).get("detail", out) if isinstance(out, dict) else out)
        return out

    # convenience
    def me(self) -> dict[str, Any]:
        return self.request("GET", "/v1/me")

    def attest(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.request("POST", "/v1/attest", {"entries": entries})

    def policy(self) -> dict[str, Any]:
        return self.request("GET", "/v1/policy")

    def decide(self, d: ActionDescriptor, recognised: bool = True) -> dict[str, Any]:
        return self.request("POST", "/v1/decide", {"descriptor": d.model_dump(mode="json"), "recognised": recognised})

    def ledger(self, **params: Any) -> list[dict[str, Any]]:
        return self.request("GET", "/v1/ledger", params=params)


# ── ledger: local + cloud sink with outbox ────────────────────────────────────
class CloudLedger(SqliteLedger):
    """A SqliteLedger that also pushes every entry to the cloud. Reads stay local."""

    def __init__(self, cloud: CloudClient, path: str = ".attest/ledger.sqlite", *, sync: bool = True):
        super().__init__(path)
        self.cloud, self.sync = cloud, sync
        self._olock = threading.Lock()
        self._cx.executescript(
            "CREATE TABLE IF NOT EXISTS outbox (entry_id TEXT PRIMARY KEY, payload TEXT NOT NULL, "
            "attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, queued_at TEXT NOT NULL)")
        self.last_push: list[dict[str, Any]] | None = None

    def append(self, entry: LedgerEntry) -> LedgerEntry:
        entry = super().append(entry)
        self._enqueue(entry)
        if self.sync:
            self.flush()
        return entry

    def _enqueue(self, entry: LedgerEntry) -> None:
        wire = {**entry.payload(), "seq": entry.seq, "hash": entry.hash}
        with self._olock:
            self._cx.execute("INSERT OR IGNORE INTO outbox (entry_id, payload, queued_at) VALUES (?,?,?)",
                             (entry.id, json.dumps(wire, default=str), datetime.now(UTC).isoformat()))

    def pending_count(self) -> int:
        with self._olock:
            return self._cx.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]

    def flush(self, batch: int = 100) -> int:
        """Push queued entries in order. Returns how many were accepted. Never raises."""
        with self._olock:
            rows = self._cx.execute("SELECT entry_id, payload FROM outbox ORDER BY queued_at LIMIT ?",
                                    (batch,)).fetchall()
        if not rows:
            return 0
        entries = [json.loads(r["payload"]) for r in rows]
        try:
            self.last_push = self.cloud.attest(entries)
        except (CloudError, OSError, ValueError) as e:
            with self._olock:
                marks = ",".join("?" * len(rows))
                sql = f"UPDATE outbox SET attempts = attempts + 1, last_error = ? WHERE entry_id IN ({marks})"
                self._cx.execute(sql, (str(e)[:200], *[r["entry_id"] for r in rows]))
            log.warning("attest cloud sink unavailable (%s); %d entries queued", e, self.pending_count())
            return 0
        with self._olock:
            marks = ",".join("?" * len(rows))
            self._cx.execute(f"DELETE FROM outbox WHERE entry_id IN ({marks})", [r["entry_id"] for r in rows])
        return len(rows)


# ── policy sync ───────────────────────────────────────────────────────────────
def cloud_policy(cloud: CloudClient, *, fallback: PolicyEngine | None = None, ctx: PolicyContext | None = None
                 ) -> PolicyEngine:
    """PolicyEngine from the org's active cloud policy; `fallback` (default: env/default rules) when unreachable."""
    try:
        pol = cloud.policy()
        engine = PolicyEngine.from_yaml(pol["yaml"], ctx)
        engine.cloud_version = pol.get("version")  # type: ignore[attr-defined]
        engine.cloud = cloud  # type: ignore[attr-defined]
        return engine
    except Exception as e:
        log.warning("attest cloud policy unavailable (%s); using local policy", e)
        return fallback or PolicyEngine.from_env(ctx)


def refresh_policy(engine: PolicyEngine) -> bool:
    cloud = getattr(engine, "cloud", None)
    if cloud is None:
        return False
    try:
        pol = cloud.policy()
    except Exception:
        return False
    if pol.get("version") != getattr(engine, "cloud_version", None):
        from attest.policy import load_yaml
        engine.rules = load_yaml(pol["yaml"])
        engine.cloud_version = pol.get("version")  # type: ignore[attr-defined]
        return True
    return False


# ── confirmations via cloud ───────────────────────────────────────────────────
class CloudStore:
    """PendingStore interface over the cloud confirm API (the cloud notifies Slack / webhook)."""

    def __init__(self, cloud: CloudClient):
        self.cloud = cloud
        self.path = ":cloud:"

    def create(self, request: ConfirmRequest, *, ttl_s: float | None = 86400, meta: dict | None = None) -> str:
        self.cloud.request("POST", "/v1/confirm", {
            "id": request.id, "resume_token": request.resume_token, "action_id": request.action_id,
            "descriptor": request.descriptor.model_dump(mode="json"), "reasons": request.reasons,
            "risk_tier": request.risk_tier, "approvers": request.approvers, "hold": request.hold, "ttl_s": ttl_s})
        return request.resume_token

    def get(self, ref: str) -> dict[str, Any] | None:
        try:
            return self.cloud.request("GET", f"/v1/confirm/{ref}")
        except CloudError as e:
            if e.status == 404:
                return None
            raise

    def decide(self, ref: str, decision: ConfirmDecision) -> bool:
        try:
            self.cloud.request("POST", f"/v1/confirm/{ref}/decide", {
                "status": "approved" if decision.status == "edited" else decision.status, "edits": decision.edits,
                "note": decision.note, "approver": decision.approver})
            return True
        except CloudError as e:
            if e.status in (404, 409):
                return False
            raise

    def set_meta(self, ref: str, **meta: Any) -> None:  # cloud owns meta
        pass

    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.cloud.request("GET", "/v1/confirm", params={"status": "pending", "limit": limit})

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
                              hold=row["hold"], channel=row["channel"] or "cloud", id=row["id"],
                              resume_token=row["resume_token"],
                              requested_at=datetime.fromisoformat(row["requested_at"]))

    def decision(self, ref: str) -> ConfirmDecision | None:
        row = self.get(ref)
        if row is None:
            return None
        if row["status"] == "pending":
            return ConfirmDecision("pending", channel=row["channel"] or "cloud")
        decided = datetime.fromisoformat(row["decided_at"]) if row["decided_at"] else datetime.now(UTC)
        return ConfirmDecision(row["status"], row["approver"], row["edits"], row["note"],
                              channel=row["channel"] or "cloud", decided_at=decided)

    def wait(self, ref: str, timeout_s: float | None, poll_s: float = 2.0) -> ConfirmDecision:
        deadline = time.monotonic() + timeout_s if timeout_s else None
        while True:
            try:
                dec = self.decision(ref)
            except (CloudError, OSError) as e:
                log.warning("attest cloud poll failed: %s", e)
                dec = ConfirmDecision("pending", channel="cloud")
            if dec is None:
                return ConfirmDecision("rejected", note="unknown request", channel="cloud")
            if not dec.pending:
                return dec
            if deadline is not None and time.monotonic() >= deadline:
                return ConfirmDecision("expired", note=f"no decision within {timeout_s}s", channel="cloud")
            time.sleep(poll_s)


__all__ = ["CloudClient", "CloudError", "CloudLedger", "CloudStore", "cloud_policy", "refresh_policy"]
_ = sqlite3
