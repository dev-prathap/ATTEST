"""Verification ladder (doc 03 §4). A level, never a boolean.

  verified          L3  read-back recipe matched                     (P1.2)
  verified-custom   L2  customer `verify=` function returned true
  acknowledged      L1  result carries an id / success; nothing read back
  attested-only     L0  recorded; nothing checkable
  unverified        —   a check ran and CONTRADICTED the claimed result — surfaced loudly

Rules: a check that could not run (exception, missing id) never yields `unverified`; that is
`acknowledged` / `attested-only` with the error in evidence. Only a contradiction is `unverified`.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from attest.descriptor import ActionDescriptor
from attest.ledger.models import VerificationRecord
from attest.verify.drivers import ack as ack_driver

log = logging.getLogger("attest.verify")


class Level(StrEnum):
    VERIFIED = "verified"
    VERIFIED_CUSTOM = "verified-custom"
    ACKNOWLEDGED = "acknowledged"
    ATTESTED_ONLY = "attested-only"
    UNVERIFIED = "unverified"


class ReadBackDriver:
    """P1.2 interface. `supports(d)`; `fetch(d, result)` → fetched; `compare(d, fetched)` → (matched, evidence)."""

    name = "driver"

    def supports(self, d: ActionDescriptor) -> bool:  # pragma: no cover - interface
        return False

    def fetch(self, d: ActionDescriptor, result: Any) -> Any:  # pragma: no cover - interface
        raise NotImplementedError

    def compare(self, d: ActionDescriptor, fetched: Any) -> tuple[bool, dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError


def _now() -> datetime:
    return datetime.now(UTC)


def _record(level: Level, method: str, matched: bool | None, evidence: dict[str, Any]) -> VerificationRecord:
    if level == Level.UNVERIFIED:
        log.warning("UNVERIFIED: read-back contradicted the claimed result (%s): %s", method, evidence)
    return VerificationRecord(level=level.value, method=method, matched=matched, evidence=evidence, checked_at=_now())


def _custom_sync(fn: Callable, result: Any, d: ActionDescriptor) -> VerificationRecord:
    try:
        sig = inspect.signature(fn)
        out = fn(result, d) if len(sig.parameters) >= 2 else fn(result)
    except Exception as e:  # check could not run — not a contradiction
        return _degrade(result, "custom", f"{type(e).__name__}: {e}")
    return _from_custom(out, result)


async def _custom_async(fn: Callable, result: Any, d: ActionDescriptor) -> VerificationRecord:
    try:
        sig = inspect.signature(fn)
        out = fn(result, d) if len(sig.parameters) >= 2 else fn(result)
        if inspect.isawaitable(out):
            out = await out
    except Exception as e:
        return _degrade(result, "custom", f"{type(e).__name__}: {e}")
    return _from_custom(out, result)


def _from_custom(out: Any, result: Any) -> VerificationRecord:
    evidence: dict[str, Any] = {}
    if isinstance(out, tuple) and len(out) == 2 and isinstance(out[1], dict):
        out, evidence = out
    if out is None:
        return _degrade(result, "custom", "verify function returned None")
    if out:
        return _record(Level.VERIFIED_CUSTOM, "custom", True, evidence)
    return _record(Level.UNVERIFIED, "custom", False, evidence or {"detail": "verify function returned false"})


def _degrade(result: Any, method: str, error: str) -> VerificationRecord:
    ok, ev = ack_driver.acknowledged(result)
    ev["check_error"] = error
    return _record(Level.ACKNOWLEDGED if ok else Level.ATTESTED_ONLY, method, None, ev)


def _read_back(d: ActionDescriptor, result: Any, drivers: list[ReadBackDriver]) -> VerificationRecord | None:
    for drv in drivers:
        if not drv.supports(d):
            continue
        method = f"read-back:{drv.name}"
        try:
            fetched = drv.fetch(d, result)
        except Exception as e:
            return _degrade(result, method, f"fetch failed: {type(e).__name__}: {e}")
        if fetched is None:
            return _degrade(result, method, "read-back returned nothing to compare")
        try:
            matched, evidence = drv.compare(d, fetched)
        except Exception as e:
            return _degrade(result, method, f"compare failed: {type(e).__name__}: {e}")
        return _record(Level.VERIFIED if matched else Level.UNVERIFIED, method, matched, evidence)
    return None


def verify(d: ActionDescriptor, result: Any, *, custom: Callable | None = None,
           drivers: list[ReadBackDriver] | None = None) -> VerificationRecord:
    """Highest available rung: read-back driver (L3) → custom (L2) → ack (L1) → attested-only (L0)."""
    rb = _read_back(d, result, drivers or [])
    if rb is not None:
        return rb
    if custom is not None:
        if inspect.iscoroutinefunction(custom):
            return asyncio.run(_custom_async(custom, result, d))
        return _custom_sync(custom, result, d)
    ok, ev = ack_driver.acknowledged(result)
    return _record(Level.ACKNOWLEDGED if ok else Level.ATTESTED_ONLY, "ack" if ok else "none", None, ev)


async def averify(d: ActionDescriptor, result: Any, *, custom: Callable | None = None,
                  drivers: list[ReadBackDriver] | None = None) -> VerificationRecord:
    rb = _read_back(d, result, drivers or [])
    if rb is not None:
        return rb
    if custom is not None:
        return await _custom_async(custom, result, d)
    ok, ev = ack_driver.acknowledged(result)
    return _record(Level.ACKNOWLEDGED if ok else Level.ATTESTED_ONLY, "ack" if ok else "none", None, ev)
