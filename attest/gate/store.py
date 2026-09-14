"""Pending confirmations, persisted — so a Slack button, a web inbox, a webhook, or an MCP `attest_resume`
call can decide a request that was raised in another process, and the caller can resume later.

Lives in the same SQLite file as the ledger by default (`.attest/ledger.sqlite`), separate table."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from attest.descriptor import ActionDescriptor
from attest.gate import ConfirmDecision, ConfirmRequest

_SCHEMA = """
CREATE TABLE IF NOT EXISTS confirm_request (
    id            TEXT PRIMARY KEY,
    resume_token  TEXT NOT NULL UNIQUE,
    action_id     TEXT NOT NULL,
    status        TEXT NOT NULL,             -- pending | approved | rejected | edited | expired
    channel       TEXT,
    descriptor    TEXT NOT NULL,             -- JSON incl. params (needed to resume)
    reasons       TEXT NOT NULL,
    risk_tier     TEXT NOT NULL,
    approvers     TEXT NOT NULL,
    hold          INTEGER NOT NULL DEFAULT 0,
    approver      TEXT,
    edits         TEXT,
    note          TEXT,
    requested_at  TEXT NOT NULL,
    decided_at    TEXT,
    expires_at    TEXT,
    meta          TEXT NOT NULL DEFAULT '{}' -- channel-specific pointers (slack ts, message ids)
);
CREATE INDEX IF NOT EXISTS idx_confirm_status ON confirm_request(status, requested_at);
"""


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _parse(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


class PendingStore:
    def __init__(self, path: str | Path = ".attest/ledger.sqlite"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cx = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=10)
        self._cx.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self._cx.execute("PRAGMA journal_mode=WAL")
        self._cx.executescript(_SCHEMA)

    # ── write ─────────────────────────────────────────────────────────────
    def create(self, request: ConfirmRequest, *, ttl_s: float | None = None, meta: dict[str, Any] | None = None) -> str:
        expires = datetime.now(UTC) + timedelta(seconds=ttl_s) if ttl_s else None
        with self._lock:
            self._cx.execute(
                "INSERT INTO confirm_request (id,resume_token,action_id,status,channel,descriptor,reasons,risk_tier,"
                "approvers,hold,requested_at,expires_at,meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (request.id, request.resume_token, request.action_id, "pending", request.channel,
                 request.descriptor.model_dump_json(), json.dumps(request.reasons), request.risk_tier,
                 json.dumps(request.approvers), int(request.hold), _iso(request.requested_at), _iso(expires),
                 json.dumps(meta or {}, default=str)))
        return request.resume_token

    def decide(self, request_id: str, decision: ConfirmDecision) -> bool:
        """Record a decision. Returns False when the request is unknown or already decided (first decision wins)."""
        with self._lock:
            cur = self._cx.execute(
                "UPDATE confirm_request SET status=?, approver=?, edits=?, note=?, decided_at=?, "
                "channel=COALESCE(?, channel) WHERE (id=? OR resume_token=?) AND status='pending'",
                (decision.status, decision.approver, json.dumps(decision.edits) if decision.edits else None,
                 decision.note, _iso(decision.decided_at), decision.channel, request_id, request_id))
            return cur.rowcount == 1

    def set_meta(self, request_id: str, **meta: Any) -> None:
        with self._lock:
            row = self._cx.execute("SELECT meta FROM confirm_request WHERE id=? OR resume_token=?",
                                   (request_id, request_id)).fetchone()
            if row is None:
                return
            merged = {**json.loads(row["meta"]), **meta}
            self._cx.execute("UPDATE confirm_request SET meta=? WHERE id=? OR resume_token=?",
                             (json.dumps(merged, default=str), request_id, request_id))

    def expire_overdue(self) -> int:
        now = _iso(datetime.now(UTC))
        with self._lock:
            cur = self._cx.execute("UPDATE confirm_request SET status='expired', decided_at=? WHERE status='pending' "
                                   "AND expires_at IS NOT NULL AND expires_at < ?", (now, now))
            return cur.rowcount

    # ── read ──────────────────────────────────────────────────────────────
    def get(self, request_id_or_token: str) -> dict[str, Any] | None:
        self.expire_overdue()
        with self._lock:
            row = self._cx.execute("SELECT * FROM confirm_request WHERE id=? OR resume_token=?",
                                   (request_id_or_token, request_id_or_token)).fetchone()
        return self._row(row) if row else None

    def find_pending(self, qualified_name: str, params_hash: str) -> dict[str, Any] | None:
        """The open request for the same action + params — used when a framework replays the node (interrupt)."""
        for row in self.pending():
            d = row["descriptor"]
            name = f"{d.get('system')}.{d.get('verb')}" + (f":{d['target']}" if d.get("target") else "")
            if name == qualified_name and d.get("params_hash") == params_hash:
                return row
        return None

    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        self.expire_overdue()
        with self._lock:
            rows = self._cx.execute("SELECT * FROM confirm_request WHERE status='pending' ORDER BY requested_at "
                                    "LIMIT ?", (limit,)).fetchall()
        return [self._row(r) for r in rows]

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._cx.execute("SELECT * FROM confirm_request ORDER BY requested_at DESC LIMIT ?",
                                    (limit,)).fetchall()
        return [self._row(r) for r in rows]

    def request(self, request_id_or_token: str) -> ConfirmRequest | None:
        row = self.get(request_id_or_token)
        if row is None:
            return None
        return ConfirmRequest(action_id=row["action_id"], descriptor=ActionDescriptor.model_validate(row["descriptor"]),
                              reasons=row["reasons"], risk_tier=row["risk_tier"], approvers=row["approvers"],
                              hold=bool(row["hold"]), channel=row["channel"] or "store", id=row["id"],
                              resume_token=row["resume_token"], requested_at=_parse(row["requested_at"]))

    def decision(self, request_id_or_token: str) -> ConfirmDecision | None:
        row = self.get(request_id_or_token)
        if row is None:
            return None
        if row["status"] == "pending":
            return ConfirmDecision("pending", channel=row["channel"] or "store")
        return ConfirmDecision(row["status"], row["approver"], row["edits"], row["note"],
                              channel=row["channel"] or "store",
                              decided_at=_parse(row["decided_at"]) or datetime.now(UTC))

    def wait(self, request_id_or_token: str, timeout_s: float | None, poll_s: float = 0.5) -> ConfirmDecision:
        """Block until decided, or until `timeout_s` elapses ⇒ marks the request expired."""
        deadline = time.monotonic() + timeout_s if timeout_s else None
        while True:
            dec = self.decision(request_id_or_token)
            if dec is None:
                return ConfirmDecision("rejected", note="unknown request", channel="store")
            if dec.status != "pending":
                return dec
            if deadline is not None and time.monotonic() >= deadline:
                self.decide(request_id_or_token, ConfirmDecision("expired", note=f"no decision within {timeout_s}s",
                                                                 channel="store"))
                return self.decision(request_id_or_token) or dec
            time.sleep(poll_s)

    @staticmethod
    def _row(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        for k in ("descriptor", "reasons", "approvers", "meta"):
            d[k] = json.loads(d[k]) if d[k] else None
        d["edits"] = json.loads(d["edits"]) if d["edits"] else None
        d["hold"] = bool(d["hold"])
        return d

    def close(self) -> None:
        with self._lock:
            self._cx.close()
