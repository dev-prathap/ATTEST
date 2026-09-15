"""External anchoring (P3.5): publish a checkpoint's hash somewhere you don't control, so even the operator
cannot rewrite history after the fact. Pluggable:

  FileAnchor(path)      append `{scope, seq, hash, signed_at, anchored_at}` to an append-only log (e.g. a git repo,
                        a WORM bucket mount, a shared drive)
  HttpAnchor(url, key)  POST the same record to a transparency / timestamping service; keeps the receipt
  GitAnchor(repo)       commit the record into a git repository (history is the log)

`attest anchor` anchors the newest checkpoint; `verify_anchor()` recomputes and compares.
"""
from __future__ import annotations

import json
import subprocess
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from attest.ledger.checkpoints import Checkpoint


@dataclass
class AnchorReceipt:
    anchor: str
    scope: str
    seq: int
    hash: str
    signed_at: str
    anchored_at: str
    ref: str | None = None  # file line no, git commit, remote id

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Anchor(Protocol):
    name: str

    def publish(self, cp: Checkpoint) -> AnchorReceipt: ...

    def lookup(self, cp: Checkpoint) -> AnchorReceipt | None: ...


def _record(cp: Checkpoint, name: str) -> dict[str, Any]:
    return {"anchor": name, "scope": cp.scope, "seq": cp.seq, "hash": cp.hash, "signed_at": cp.signed_at,
            "signature": cp.signature, "key_id": cp.key_id, "anchored_at": datetime.now(UTC).isoformat()}


class FileAnchor:
    name = "file"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def publish(self, cp: Checkpoint) -> AnchorReceipt:
        rec = _record(cp, self.name)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        n = sum(1 for _ in self.path.open())
        return AnchorReceipt(self.name, cp.scope, cp.seq, cp.hash, cp.signed_at, rec["anchored_at"], ref=f"line:{n}")

    def lookup(self, cp: Checkpoint) -> AnchorReceipt | None:
        if not self.path.exists():
            return None
        for i, line in enumerate(self.path.open(), 1):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("scope") == cp.scope and rec.get("seq") == cp.seq and rec.get("hash") == cp.hash:
                return AnchorReceipt(self.name, cp.scope, cp.seq, cp.hash, rec.get("signed_at", ""), rec.get("anchored_at", ""),
                                     ref=f"line:{i}")
        return None


class HttpAnchor:
    name = "http"

    def __init__(self, url: str, *, api_key: str | None = None, post: Any = None, get: Any = None):
        self.url, self.api_key, self._post, self._get = url.rstrip("/"), api_key, post, get

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def publish(self, cp: Checkpoint) -> AnchorReceipt:
        rec = _record(cp, self.name)
        body = json.dumps(rec).encode()
        if self._post is not None:
            out = self._post(self.url, body, self._headers())
        else:  # pragma: no cover - network
            req = urllib.request.Request(self.url, data=body, method="POST", headers=self._headers())
            with urllib.request.urlopen(req, timeout=20) as r:
                out = json.loads(r.read() or b"{}")
        return AnchorReceipt(self.name, cp.scope, cp.seq, cp.hash, cp.signed_at, rec["anchored_at"],
                             ref=str((out or {}).get("id") or (out or {}).get("receipt") or ""))

    def lookup(self, cp: Checkpoint) -> AnchorReceipt | None:
        url = f"{self.url}?scope={cp.scope}&seq={cp.seq}&hash={cp.hash}"
        if self._get is not None:
            out = self._get(url, self._headers())
        else:  # pragma: no cover - network
            req = urllib.request.Request(url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=20) as r:
                out = json.loads(r.read() or b"null")
        if not out:
            return None
        return AnchorReceipt(self.name, cp.scope, cp.seq, cp.hash, out.get("signed_at", cp.signed_at), out.get("anchored_at", ""),
                             ref=str(out.get("id", "")))


class GitAnchor:
    name = "git"

    def __init__(self, repo: str | Path, subdir: str = "anchors"):
        self.repo, self.subdir = Path(repo), subdir

    def publish(self, cp: Checkpoint) -> AnchorReceipt:
        rec = _record(cp, self.name)
        d = self.repo / self.subdir
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{cp.scope.replace(':', '_')}-{cp.seq}.json"
        f.write_text(json.dumps(rec, indent=1))
        subprocess.run(["git", "-C", str(self.repo), "add", str(f.relative_to(self.repo))], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", f"anchor {cp.scope} seq {cp.seq} {cp.hash[:12]}"],
                       check=True, capture_output=True)
        sha = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        return AnchorReceipt(self.name, cp.scope, cp.seq, cp.hash, cp.signed_at, rec["anchored_at"], ref=sha)

    def lookup(self, cp: Checkpoint) -> AnchorReceipt | None:
        f = self.repo / self.subdir / f"{cp.scope.replace(':', '_')}-{cp.seq}.json"
        if not f.exists():
            return None
        rec = json.loads(f.read_text())
        if rec.get("hash") != cp.hash:
            return None
        return AnchorReceipt(self.name, cp.scope, cp.seq, cp.hash, rec.get("signed_at", ""), rec.get("anchored_at", ""), ref=str(f))


def verify_anchor(anchor: Anchor, cp: Checkpoint) -> bool:
    """True when the anchor holds exactly this (scope, seq, hash)."""
    r = anchor.lookup(cp)
    return r is not None and r.hash == cp.hash and r.seq == cp.seq
