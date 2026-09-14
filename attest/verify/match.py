"""Field-level comparison between intent (the descriptor's params) and what the system of record holds."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_ID_KEYS = {"id", "Id", "ID", "_id", "uuid", "key"}


@dataclass
class MatchReport:
    """`matched` is the verdict; `compared` says how much intent was actually checked. A report with
    `compared == 0` is existence only — the ladder records that as `acknowledged` with `exists`, never `verified`."""

    matched: bool
    exists: bool = True
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)  # name → {want, got, ok}
    checks: dict[str, bool] = field(default_factory=dict)  # named boolean checks (label:SENT, ts, thread)
    notes: list[str] = field(default_factory=list)

    @property
    def compared(self) -> int:
        return len(self.fields) + len(self.checks)

    @property
    def failed(self) -> list[str]:
        return [k for k, v in self.fields.items() if not v["ok"]] + [k for k, ok in self.checks.items() if not ok]

    def field_(self, name: str, want: Any, got: Any, ok: bool | None = None) -> bool:
        ok = equal(want, got) if ok is None else ok
        self.fields[name] = {"want": _short(want), "got": _short(got), "ok": ok}
        if not ok:
            self.matched = False
        return ok

    def check(self, name: str, ok: bool, **info: Any) -> bool:
        self.checks[name] = bool(ok)
        if info:
            self.notes.append(f"{name}: {info}")
        if not ok:
            self.matched = False
        return ok

    def evidence(self) -> dict[str, Any]:
        ev: dict[str, Any] = {"exists": self.exists, "compared": self.compared}
        if self.fields:
            ev["fields"] = self.fields
        if self.checks:
            ev["checks"] = self.checks
        if self.failed:
            ev["failed"] = self.failed
        if self.notes:
            ev["notes"] = self.notes[:10]
        return ev


def _short(v: Any, n: int = 120) -> Any:
    if isinstance(v, str) and len(v) > n:
        return v[:n] + "…"
    if isinstance(v, (dict, list)) and len(str(v)) > n:
        return f"<{type(v).__name__} len={len(v)}>"
    return v


def norm(v: Any) -> Any:
    if isinstance(v, str):
        s = " ".join(v.split()).strip()
        return s.lower() if _EMAIL.fullmatch(s) else s
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [norm(x) for x in v]
    return v


def equal(want: Any, got: Any) -> bool:
    if want is None:
        return True  # nothing intended, nothing to contradict
    a, b = norm(want), norm(got)
    if isinstance(a, list) and not isinstance(b, list):
        b = _emails(b) if isinstance(b, str) and _EMAIL.search(b) else [b]
    if isinstance(a, list) and isinstance(b, list):
        return all(x in b for x in a)
    if isinstance(a, str) and isinstance(b, str) and _EMAIL.fullmatch(a):
        return a in _emails(b)
    return a == b


def _emails(s: str) -> list[str]:
    return [e.lower() for e in _EMAIL.findall(s)]


def emails(v: Any) -> list[str]:
    if isinstance(v, (list, tuple)):
        return [e for x in v for e in emails(x)]
    return _emails(str(v or ""))


def compare_overlap(report: MatchReport, want: dict[str, Any], got: dict[str, Any], *, skip: set[str] | None = None
                    ) -> MatchReport:
    """Compare every intended field that the fetched object also carries (top-level, or under `properties`/`data`)."""
    skip = (skip or set()) | _ID_KEYS
    sources = [got] + [got[k] for k in ("properties", "data", "fields", "attributes") if isinstance(got.get(k), dict)]
    for k, v in want.items():
        if k in skip or v is None or isinstance(v, (dict, list)) and not v:
            continue
        for src in sources:
            if k in src:
                report.field_(k, v, src[k])
                break
    return report
