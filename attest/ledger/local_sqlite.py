"""Append-only, hash-chained SQLite ledger. Works with no cloud. Thread-safe via a lock; every append is
one transaction that reads the tail and writes the next link."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from attest.ledger import checkpoints as cps
from attest.ledger import hashchain
from attest.ledger.models import LedgerEntry

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger (
    seq          INTEGER PRIMARY KEY,
    id           TEXT NOT NULL UNIQUE,
    action_id    TEXT NOT NULL,
    run_id       TEXT,
    agent        TEXT,
    actor        TEXT,
    system       TEXT,
    verb         TEXT,
    decision     TEXT NOT NULL,
    level        TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    payload      TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    hash         TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_ledger_run ON ledger(run_id);
CREATE INDEX IF NOT EXISTS idx_ledger_agent ON ledger(agent);
CREATE TABLE IF NOT EXISTS checkpoint (
    seq        INTEGER PRIMARY KEY,
    hash       TEXT NOT NULL,
    signed_at  TEXT NOT NULL,
    scope      TEXT NOT NULL,
    signature  TEXT,
    key_id     TEXT
);
"""


class SqliteLedger:
    def __init__(self, path: str | Path = ".attest/ledger.sqlite", *, signing_key: str | None = None):
        self.path = str(path)
        self.signing_key = signing_key if signing_key is not None else os.environ.get("ATTEST_LEDGER_KEY")
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cx = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._cx.row_factory = sqlite3.Row
        self._cx.execute("PRAGMA journal_mode=WAL") if self.path != ":memory:" else None
        self._cx.executescript(_SCHEMA)

    # ── write ─────────────────────────────────────────────────────────────
    def append(self, entry: LedgerEntry) -> LedgerEntry:
        with self._lock:
            self._cx.execute("BEGIN IMMEDIATE")
            try:
                tail = self._cx.execute("SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
                seq = (tail["seq"] + 1) if tail else 1
                prev = tail["hash"] if tail else hashchain.GENESIS
                payload = entry.payload()
                ph = hashchain.payload_hash(payload)
                h = hashchain.entry_hash(prev, seq, ph)
                d = payload["descriptor"]
                self._cx.execute(
                    "INSERT INTO ledger (seq,id,action_id,run_id,agent,actor,system,verb,decision,level,created_at,"
                    "payload,payload_hash,prev_hash,hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (seq, entry.id, entry.action_id, entry.run_id, entry.agent, entry.actor, d.get("system"),
                     d.get("verb"), entry.decision, entry.verification.level, payload["created_at"],
                     json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str), ph, prev, h),
                )
                self._cx.execute("COMMIT")
            except Exception:
                self._cx.execute("ROLLBACK")
                raise
        entry.seq, entry.prev_hash, entry.payload_hash, entry.hash = seq, prev, ph, h
        return entry

    # ── read ──────────────────────────────────────────────────────────────
    def _rows(self, where: str = "", args: tuple = (), limit: int | None = None, desc: bool = False) -> list[dict]:
        order = "DESC" if desc else "ASC"
        sql = "SELECT * FROM ledger" + (f" WHERE {where}" if where else "") + f" ORDER BY seq {order}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        with self._lock:
            rows = self._cx.execute(sql, args).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["payload"] = json.loads(d["payload"])
        return d

    def entries(self, *, run_id: str | None = None, agent: str | None = None, level: str | None = None,
                limit: int | None = None, newest_first: bool = False) -> list[LedgerEntry]:
        clauses, args = [], []
        for col, val in (("run_id", run_id), ("agent", agent), ("level", level)):
            if val is not None:
                clauses.append(f"{col} = ?")
                args.append(val)
        return [self._to_entry(r) for r in self._rows(" AND ".join(clauses), tuple(args), limit, newest_first)]

    def get(self, action_id: str) -> LedgerEntry | None:
        rows = self._rows("action_id = ?", (action_id,), 1)
        return self._to_entry(rows[0]) if rows else None

    def last(self) -> LedgerEntry | None:
        rows = self._rows(limit=1, desc=True)
        return self._to_entry(rows[0]) if rows else None

    def count(self) -> int:
        with self._lock:
            return self._cx.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]

    @staticmethod
    def _to_entry(row: dict[str, Any]) -> LedgerEntry:
        e = LedgerEntry.model_validate(row["payload"])
        e.seq, e.prev_hash, e.payload_hash, e.hash = row["seq"], row["prev_hash"], row["payload_hash"], row["hash"]
        return e

    # ── integrity ─────────────────────────────────────────────────────────
    def verify_chain(self, *, since_checkpoint: bool = False) -> hashchain.ChainReport:
        """Verifies from genesis, or from the newest checkpoint that precedes the first retained row (after prune).

        Verification is linear in the number of rows. `since_checkpoint=True` starts at the newest checkpoint
        instead, which bounds the work on a long ledger: everything up to that checkpoint was already verified
        when it was signed (and, if it was anchored, by anyone holding the anchor)."""
        anchor = None
        if since_checkpoint:
            with self._lock:
                cp = self._cx.execute("SELECT seq, hash FROM checkpoint ORDER BY seq DESC LIMIT 1").fetchone()
            if cp is not None:
                anchor = (cp["seq"], cp["hash"])
                return hashchain.verify(self._rows("seq > ?", (cp["seq"],)), anchor=anchor)
        rows = self._rows()
        if rows and rows[0]["seq"] > 1:
            with self._lock:
                cp = self._cx.execute("SELECT seq, hash FROM checkpoint WHERE seq = ?",
                                      (rows[0]["seq"] - 1,)).fetchone()
            if cp is None:
                return hashchain.ChainReport(False, 0, rows[0]["seq"], [f"rows before seq {rows[0]['seq']} are missing "
                                                                         "and no checkpoint anchors the chain"])
            anchor = (cp["seq"], cp["hash"])
        return hashchain.verify(rows, anchor=anchor)

    # ── checkpoints & retention ───────────────────────────────────────────
    def checkpoint(self, scope: str = "local") -> cps.Checkpoint | None:
        """Sign the current head. Returns None on an empty ledger."""
        tail = self.last()
        if tail is None:
            return None
        cp = cps.sign(tail.seq, tail.hash, key=self.signing_key, scope=scope)  # type: ignore[arg-type]
        with self._lock:
            self._cx.execute("INSERT OR REPLACE INTO checkpoint (seq, hash, signed_at, scope, signature, key_id) "
                             "VALUES (?,?,?,?,?,?)", (cp.seq, cp.hash, cp.signed_at, cp.scope, cp.signature, cp.key_id))
        return cp

    def checkpoints(self) -> list[cps.Checkpoint]:
        with self._lock:
            rows = self._cx.execute("SELECT * FROM checkpoint ORDER BY seq").fetchall()
        return [cps.Checkpoint(r["seq"], r["hash"], r["signed_at"], r["scope"], r["signature"], r["key_id"])
                for r in rows]

    def prune(self, *, older_than_days: int | None = None, before_seq: int | None = None) -> int:
        """Retention: drop rows older than N days (or below a seq), keeping the chain verifiable by writing a
        checkpoint at the last pruned row. Returns rows removed. Never prunes past the head."""
        with self._lock:
            if before_seq is None:
                if older_than_days is None:
                    raise ValueError("prune needs older_than_days or before_seq")
                cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat()
                row = self._cx.execute("SELECT MAX(seq) AS s FROM ledger WHERE created_at < ?", (cutoff,)).fetchone()
                before_seq = (row["s"] or 0) + 1
            head = self._cx.execute("SELECT MAX(seq) AS s FROM ledger").fetchone()["s"] or 0
            before_seq = min(before_seq, head)  # always keep the head row
            last = self._cx.execute("SELECT seq, hash FROM ledger WHERE seq < ? ORDER BY seq DESC LIMIT 1",
                                    (before_seq,)).fetchone()
            if last is None:
                return 0
            cp = cps.sign(last["seq"], last["hash"], key=self.signing_key, scope="local")  # type: ignore[arg-type]
            self._cx.execute("BEGIN IMMEDIATE")
            try:
                self._cx.execute("INSERT OR REPLACE INTO checkpoint (seq, hash, signed_at, scope, signature, key_id) "
                                 "VALUES (?,?,?,?,?,?)",
                                 (cp.seq, cp.hash, cp.signed_at, cp.scope, cp.signature, cp.key_id))
                cur = self._cx.execute("DELETE FROM ledger WHERE seq < ?", (before_seq,))
                self._cx.execute("COMMIT")
            except Exception:
                self._cx.execute("ROLLBACK")
                raise
            return cur.rowcount

    def export(self, fmt: str = "json") -> str:
        rows = self._rows()
        if fmt == "json":
            return json.dumps([{**r["payload"], "seq": r["seq"], "prev_hash": r["prev_hash"], "hash": r["hash"]}
                               for r in rows], indent=2, default=str)
        if fmt == "csv":
            import csv
            import io
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["seq", "created_at", "run_id", "agent", "actor", "system", "verb", "decision", "level", "hash"])
            for r in rows:
                w.writerow([r["seq"], r["created_at"], r["run_id"], r["agent"], r["actor"], r["system"], r["verb"],
                            r["decision"], r["level"], r["hash"]])
            return buf.getvalue()
        if fmt in ("ietf", "jsonl"):
            from attest.ledger.exports import ietf_jsonl
            return ietf_jsonl([self._to_entry(r) for r in rows])
        if fmt in ("eu-ai-act", "eu_ai_act"):
            from attest.ledger.exports import eu_ai_act_pack
            rep = self.verify_chain()
            return json.dumps(eu_ai_act_pack(
                [self._to_entry(r) for r in rows], checkpoints=[c.to_dict() for c in self.checkpoints()],
                chain={"ok": rep.ok, "checked": rep.checked, "head": rows[-1]["hash"] if rows else None},
                signing_key=self.signing_key), indent=2, default=str)
        raise ValueError(f"unknown export format {fmt!r}")

    def close(self) -> None:
        with self._lock:
            self._cx.close()
