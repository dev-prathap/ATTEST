"""The Attest client and the `@action` decorator: decide → gate → execute → verify → attest.

    at = Attest(agent="followup-agent@v3", actor="ram@acme.com")

    @at.action(system="gmail", verb="send", target="to")
    def send_email(to, subject, body): ...

The customer's function is the execution step. Attest never calls the vendor to write.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import inspect
import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from attest.descriptor import ActionDescriptor, new_id
from attest.exceptions import ActionPending, ActionRefused, ActionRejected, AttestError
from attest.gate import AutoGate, ConfirmDecision, ConfirmRequest, Gate, gate_from_env
from attest.gate.store import PendingStore
from attest.ledger import ConfirmRecord, ExecutionRecord, LedgerEntry, SqliteLedger, preview
from attest.ledger.models import VerificationRecord
from attest.policy import PolicyContext, PolicyEngine, PolicyResult
from attest.registry import Detection, detect
from attest.verify import ReadBackDriver, averify, verify
from attest.verify.drivers.convention import ConventionDriver
from attest.verify.drivers.recipe import RecipeDriver

log = logging.getLogger("attest")

_current_run: contextvars.ContextVar[str | None] = contextvars.ContextVar("attest_run", default=None)
_current_actor: contextvars.ContextVar[str | None] = contextvars.ContextVar("attest_actor", default=None)


class ActionReceipt:
    """What `Attest.run_action` returns alongside the result — everything the ledger recorded."""

    def __init__(self, entry: LedgerEntry, result: Any, descriptor: ActionDescriptor, policy: PolicyResult,
                 confirm: ConfirmDecision | None):
        self.entry, self.result, self.descriptor, self.policy, self.confirm = entry, result, descriptor, policy, confirm

    @property
    def level(self) -> str:
        return self.entry.verification.level

    @property
    def decision(self) -> str:
        return self.entry.decision

    def __repr__(self) -> str:
        return (f"ActionReceipt({self.descriptor.qualified_name} decision={self.decision} level={self.level} "
                f"seq={self.entry.seq})")


class Attest:
    def __init__(
        self,
        *,
        ledger: SqliteLedger | None = None,
        policy: PolicyEngine | None = None,
        gate: Gate | None = None,
        agent: str | None = None,
        actor: str | None = None,
        drivers: list[ReadBackDriver] | None = None,
        readers: dict[str, Any] | None = None,
        http_get: Any = None,
        ledger_path: str | None = None,
        store: PendingStore | None = None,
    ):
        """`readers` = {"gmail": service_or_token, "slack": client_or_token, "hubspot": client_or_token} — the
        agent's own credentials, used in-process for L3 read-back. `http_get(url, params)` (or a bearer token)
        enables the convention driver for any REST API. `drivers` adds custom read-back drivers first."""
        self.ledger = ledger or SqliteLedger(ledger_path or os.environ.get("ATTEST_LEDGER", ".attest/ledger.sqlite"))
        self.policy = policy or PolicyEngine.from_env(PolicyContext())
        self.gate = gate or gate_from_env()
        self.agent = agent or os.environ.get("ATTEST_AGENT")
        self.actor = actor or os.environ.get("ATTEST_ACTOR")
        self.store = store or getattr(self.gate, "store", None) or PendingStore(self.ledger.path)
        self._resumables: dict[str, dict[str, Any]] = {}
        self.recipes = RecipeDriver(readers)
        self.convention = ConventionDriver(http_get) if http_get is not None else None
        self.drivers = list(drivers or [])
        from attest.telemetry import Telemetry
        self.telemetry = Telemetry()

    def _drivers(self, readers: dict[str, Any] | None = None, http_get: Any = None) -> list[ReadBackDriver]:
        out: list[ReadBackDriver] = list(self.drivers)
        out.append(self.recipes.with_readers(readers))
        conv = ConventionDriver(http_get) if http_get is not None else self.convention
        if conv is not None:
            out.append(conv)
        return out

    @classmethod
    def cloud(cls, url: str | None = None, api_key: str | None = None, *, wait: bool = True,
              timeout_s: float | None = 900, ledger_path: str | None = None, transport: Any = None,
              **kw: Any) -> Attest:
        """A client wired to Attest Cloud: synced ledger, cloud policy, cloud-routed confirmations."""
        from attest.cloud import CloudClient, CloudLedger, CloudStore, cloud_policy
        from attest.gate import StoreGate
        cloud = CloudClient(url, api_key, transport=transport)
        ledger = CloudLedger(cloud, ledger_path or os.environ.get("ATTEST_LEDGER", ".attest/ledger.sqlite"))
        store = CloudStore(cloud)
        gate = kw.pop("gate", None) or StoreGate(store, wait=wait, timeout_s=timeout_s, poll_s=kw.pop("poll_s", 2.0))
        policy = kw.pop("policy", None) or cloud_policy(cloud, ctx=PolicyContext())
        at = cls(ledger=ledger, policy=policy, gate=gate, store=store, **kw)
        at.cloud_client = cloud  # type: ignore[attr-defined]
        return at

    # ── context ───────────────────────────────────────────────────────────
    @contextlib.contextmanager
    def run(self, run_id: str | None = None, *, actor: str | None = None):
        """Group actions under one run id (and optionally an actor) for the duration of the block."""
        t1 = _current_run.set(run_id or new_id("run"))
        t2 = _current_actor.set(actor) if actor else None
        try:
            yield _current_run.get()
        finally:
            _current_run.reset(t1)
            if t2:
                _current_actor.reset(t2)

    @staticmethod
    def current_run_id() -> str | None:
        return _current_run.get()

    # ── the decorator ─────────────────────────────────────────────────────
    def action(
        self,
        fn: Callable | None = None,
        *,
        system: str | None = None,
        verb: str | None = None,
        target: str | Callable[[dict[str, Any]], str | None] | None = None,
        risk: str | None = None,
        verify: Callable | None = None,
        tool_name: str | None = None,
        method: str | None = None,
        url: str | None = None,
        sdk_path: str | None = None,
        params: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        name: str | None = None,
        reader: Any = None,
        readers: dict[str, Any] | None = None,
        http_get: Any = None,
    ) -> Callable:
        """Wrap one function. Everything is optional: with nothing given, system/verb are inferred from the
        function name (`send_email` ⇒ unknown/send). `target` may be a param name, a literal, or a callable
        over the bound arguments. `verify` is the customer's own check (L2). `params` can reshape what is
        recorded (e.g. drop a blob) — it never changes what the function receives."""

        def decorate(func: Callable) -> Callable:
            det_kw = dict(system=system, verb=verb, tool_name=tool_name, method=method, url=url, sdk_path=sdk_path,
                          function_name=name or func.__name__)
            sig = inspect.signature(func)
            extra = {k: v for k, v in (("method", method), ("url", url), ("tool_name", tool_name),
                                       ("sdk_path", sdk_path)) if v}
            local_readers = dict(readers or {})

            def build(args: tuple, kwargs: dict) -> tuple[ActionDescriptor, Detection, dict[str, Any]]:
                bound = sig.bind_partial(*args, **kwargs)
                bound.apply_defaults()
                raw = dict(bound.arguments)
                raw.pop("self", None)
                recorded = params(raw) if params else raw
                det = detect(**det_kw)
                d = ActionDescriptor(system=det.system, verb=det.verb, target=_target(target, raw, det),
                                     params=_jsonable(recorded), actor=_current_actor.get() or self.actor,
                                     agent=self.agent, run_id=_current_run.get(), risk=risk, source=det.source,
                                     extra=extra)
                return d, det, raw

            def rb() -> dict[str, Any]:
                if reader is not None:
                    return {**local_readers, (system or "unknown"): reader}
                return local_readers

            def _resume(token: str) -> Any:
                return self.resume(token).result

            if inspect.iscoroutinefunction(func):
                @functools.wraps(func)
                async def awrapper(*args: Any, **kwargs: Any) -> Any:
                    d, det, raw = build(args, kwargs)
                    receipt = await self.arun_action(d, lambda p: func(**_rebind(sig, raw, p)),
                                                     recognised=det.recognised, verify_fn=verify,
                                                     readers=rb(), http_get=http_get)
                    return receipt.result
                awrapper.attest = self  # type: ignore[attr-defined]
                async def _aresume(token: str) -> Any:
                    return (await self.aresume(token)).result

                awrapper.resume = _aresume  # type: ignore[attr-defined]
                return awrapper

            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                d, det, raw = build(args, kwargs)
                receipt = self.run_action(d, lambda p: func(**_rebind(sig, raw, p)), recognised=det.recognised,
                                          verify_fn=verify, readers=rb(), http_get=http_get)
                return receipt.result
            wrapper.attest = self  # type: ignore[attr-defined]
            wrapper.resume = _resume  # type: ignore[attr-defined]
            return wrapper

        return decorate(fn) if fn is not None else decorate

    # ── the pipeline ──────────────────────────────────────────────────────
    def run_action(self, d: ActionDescriptor, execute: Callable[[dict[str, Any]], Any], *, recognised: bool = True,
                   verify_fn: Callable | None = None, readers: dict[str, Any] | None = None,
                   http_get: Any = None) -> ActionReceipt:
        pol = self.policy.evaluate(d, recognised=recognised)
        d.target_class = pol.target_class  # type: ignore[assignment]
        entry = self._entry(d, pol)
        if pol.decision == "refuse":
            self.ledger.append(entry)
            raise ActionRefused(d.id, pol.reasons, d)
        decision: ConfirmDecision | None = None
        if pol.decision == "ask":
            request = self._request(d, pol)
            decision = self.gate.confirm(request)
            if decision.pending:
                self._park(d, entry, request, decision, execute, verify_fn, readers, http_get)
            d, entry = self._after_confirm(d, entry, decision)
        result, rec = self._execute(d, execute)
        entry.execution = rec
        entry.verification = (verify(d.with_result(result), result, custom=verify_fn,
                                     drivers=self._drivers(readers, http_get))
                              if rec.status == "done" else VerificationRecord(level="attested-only", method="none",
                                                                              evidence={"detail": "execution failed"}))
        self.ledger.append(entry)
        self.telemetry.record(decision=pol.decision, level=entry.verification.level, system=d.system,
                              entry_point=d.extra.get("framework") or d.source)
        if rec.status == "failed":
            raise rec._exc  # type: ignore[attr-defined]
        return ActionReceipt(entry, result, d, pol, decision)

    async def arun_action(self, d: ActionDescriptor, execute: Callable[[dict[str, Any]], Any], *,
                          recognised: bool = True, verify_fn: Callable | None = None,
                          readers: dict[str, Any] | None = None, http_get: Any = None) -> ActionReceipt:
        pol = self.policy.evaluate(d, recognised=recognised)
        d.target_class = pol.target_class  # type: ignore[assignment]
        entry = self._entry(d, pol)
        if pol.decision == "refuse":
            await asyncio.to_thread(self.ledger.append, entry)
            raise ActionRefused(d.id, pol.reasons, d)
        decision: ConfirmDecision | None = None
        if pol.decision == "ask":
            request = self._request(d, pol)
            decision = await self.gate.aconfirm(request)
            if decision.pending:
                self._park(d, entry, request, decision, execute, verify_fn, readers, http_get)
            d, entry = self._after_confirm(d, entry, decision)
        result, rec = await self._aexecute(d, execute)
        entry.execution = rec
        entry.verification = (await self._averify(d, result, verify_fn, readers, http_get)
                              if rec.status == "done" else VerificationRecord(level="attested-only", method="none",
                                                                              evidence={"detail": "execution failed"}))
        await asyncio.to_thread(self.ledger.append, entry)
        if rec.status == "failed":
            raise rec._exc  # type: ignore[attr-defined]
        return ActionReceipt(entry, result, d, pol, decision)

    async def _averify(self, d: ActionDescriptor, result: Any, verify_fn: Callable | None,
                       readers: dict[str, Any] | None, http_get: Any) -> VerificationRecord:
        drivers = self._drivers(readers, http_get)
        if verify_fn is not None and inspect.iscoroutinefunction(verify_fn):
            return await averify(d.with_result(result), result, custom=verify_fn, drivers=drivers)
        return await asyncio.to_thread(verify, d.with_result(result), result, custom=verify_fn, drivers=drivers)

    # ── pending / resume (async-interrupt and MCP-pending modes) ──────────
    def _park(self, d: ActionDescriptor, entry: LedgerEntry, request: ConfirmRequest, decision: ConfirmDecision,
              execute: Callable, verify_fn: Callable | None, readers: dict[str, Any] | None, http_get: Any) -> None:
        """The gate returned `pending`: record it, remember how to execute, and hand the caller a resume token."""
        entry.confirm = ConfirmRecord(status="pending", channel=decision.channel, requested_at=request.requested_at)
        self.ledger.append(entry)
        if self.store.get(request.id) is None:  # gate did not persist it (custom gate) — we do
            self.store.create(request)
        self._resumables[request.resume_token] = {"execute": execute, "verify_fn": verify_fn, "readers": readers,
                                                  "http_get": http_get}
        raise ActionPending(d.id, request.resume_token, d)

    def resume(self, resume_token: str, execute: Callable[[dict[str, Any]], Any] | None = None, *,
               verify_fn: Callable | None = None, readers: dict[str, Any] | None = None,
               http_get: Any = None) -> ActionReceipt:
        """Continue a parked action once a human decided. `execute` may be omitted in the same process that
        parked it (the decorator / adapter remembered it); cross-process callers pass it explicitly."""
        d, entry, saved = self._unpark(resume_token, execute, verify_fn, readers, http_get)
        result, rec = self._execute(d, saved["execute"])
        entry.execution = rec
        entry.verification = (verify(d.with_result(result), result, custom=saved["verify_fn"],
                                     drivers=self._drivers(saved["readers"], saved["http_get"]))
                              if rec.status == "done" else VerificationRecord(level="attested-only", method="none",
                                                                              evidence={"detail": "execution failed"}))
        self.ledger.append(entry)
        if rec.status == "failed":
            raise rec._exc  # type: ignore[attr-defined]
        return ActionReceipt(entry, result, d, PolicyResult("ask", entry.risk_tier, entry.reasons),
                             entry_decision(entry))

    async def aresume(self, resume_token: str, execute: Callable[[dict[str, Any]], Any] | None = None, *,
                      verify_fn: Callable | None = None, readers: dict[str, Any] | None = None,
                      http_get: Any = None) -> ActionReceipt:
        d, entry, saved = self._unpark(resume_token, execute, verify_fn, readers, http_get)
        result, rec = await self._aexecute(d, saved["execute"])
        entry.execution = rec
        entry.verification = (await self._averify(d, result, saved["verify_fn"], saved["readers"], saved["http_get"])
                              if rec.status == "done" else VerificationRecord(level="attested-only", method="none",
                                                                              evidence={"detail": "execution failed"}))
        await asyncio.to_thread(self.ledger.append, entry)
        if rec.status == "failed":
            raise rec._exc  # type: ignore[attr-defined]
        return ActionReceipt(entry, result, d, PolicyResult("ask", entry.risk_tier, entry.reasons),
                             entry_decision(entry))

    def _unpark(self, token: str, execute: Callable | None, verify_fn: Callable | None,
                readers: dict[str, Any] | None, http_get: Any) -> tuple[ActionDescriptor, LedgerEntry, dict[str, Any]]:
        row = self.store.get(token)
        if row is None:
            raise AttestError(f"unknown resume token {token!r}")
        request = self.store.request(token)
        assert request is not None
        d = request.descriptor
        dec = self.store.decision(token)
        assert dec is not None
        if dec.pending:
            raise ActionPending(d.id, request.resume_token, d)
        saved = self._resumables.pop(request.resume_token, None) or {}
        if execute is not None:
            saved["execute"] = execute
        if "execute" not in saved:
            raise AttestError("resume needs `execute=`: this process did not park the action")
        saved.setdefault("verify_fn", verify_fn)
        saved.setdefault("readers", readers)
        saved.setdefault("http_get", http_get)
        if verify_fn is not None:
            saved["verify_fn"] = verify_fn
        if readers is not None:
            saved["readers"] = readers
        if http_get is not None:
            saved["http_get"] = http_get
        entry = LedgerEntry.from_descriptor(d, decision="ask", risk_tier=request.risk_tier, reasons=request.reasons,
                                            rules_fired=["resume"], target_class=d.target_class,
                                            resumed_from=request.id)
        entry.confirm = ConfirmRecord(status=dec.status, channel=dec.channel, approver=dec.approver,
                                      requested_at=request.requested_at, decided_at=dec.decided_at, edits=dec.edits,
                                      note=dec.note)
        if not dec.approved:
            self.ledger.append(entry)
            raise ActionRejected(d.id, dec.approver, dec.note or dec.status, d)
        if dec.edits:
            d = d.model_copy(update={"params": {**d.params, **_jsonable(dec.edits)}})
            entry.descriptor, entry.params_hash, entry.params_preview = d.to_ledger(), d.params_hash, preview(d.params)
        return d, entry, saved

    # ── API-only entry point (doc 03 §2 #5): record what already happened ──
    def attest(self, *, system: str = "unknown", verb: str = "write", target: str | None = None,
               params: dict[str, Any] | None = None, result: Any = None, verified: bool | None = None,
               evidence: dict[str, Any] | None = None, error: str | None = None, **kw: Any) -> LedgerEntry:
        """Record an action that the caller executed elsewhere. `verified=True` with evidence ⇒ verified-custom;
        `verified=False` ⇒ unverified; None ⇒ ack ladder over `result`."""
        d = ActionDescriptor(system=system, verb=verb, target=target, params=_jsonable(params or {}),
                             actor=kw.get("actor") or _current_actor.get() or self.actor,
                             agent=kw.get("agent") or self.agent,
                             run_id=kw.get("run_id") or _current_run.get(), source="api")
        pol = self.policy.evaluate(d)
        d.target_class = pol.target_class  # type: ignore[assignment]
        entry = self._entry(d, pol)
        entry.decision = "recorded"
        entry.execution = ExecutionRecord(status="failed" if error else "done", result_hash=_hash_or_none(result),
                                          result_preview=preview(result), error=error, finished_at=datetime.now(UTC))
        if verified is True:
            entry.verification = VerificationRecord(level="verified-custom", method="caller", matched=True,
                                                    evidence=evidence or {}, checked_at=datetime.now(UTC))
        elif verified is False:
            entry.verification = VerificationRecord(level="unverified", method="caller", matched=False,
                                                    evidence=evidence or {}, checked_at=datetime.now(UTC))
        else:
            entry.verification = verify(d, result)
        return self.ledger.append(entry)

    # ── helpers ───────────────────────────────────────────────────────────
    def _entry(self, d: ActionDescriptor, pol: PolicyResult) -> LedgerEntry:
        return LedgerEntry.from_descriptor(d, decision=pol.decision, risk_tier=pol.risk_tier, reasons=pol.reasons,
                                           rules_fired=pol.rules_fired, target_class=pol.target_class)

    def _request(self, d: ActionDescriptor, pol: PolicyResult) -> ConfirmRequest:
        return ConfirmRequest(d.id, d, pol.reasons, pol.risk_tier, pol.approvers, pol.hold,
                              approver_members=pol.approver_members, channel=self.gate.name)

    def _after_confirm(self, d: ActionDescriptor, entry: LedgerEntry, dec: ConfirmDecision
                       ) -> tuple[ActionDescriptor, LedgerEntry]:
        entry.confirm = ConfirmRecord(status=dec.status, channel=dec.channel, approver=dec.approver,
                                      requested_at=entry.created_at, decided_at=dec.decided_at, edits=dec.edits,
                                      note=dec.note)
        if not dec.approved:
            self.ledger.append(entry)
            raise ActionRejected(d.id, dec.approver, dec.note, d)
        if dec.edits:
            d = d.model_copy(update={"params": {**d.params, **_jsonable(dec.edits)}})
            entry.descriptor, entry.params_hash, entry.params_preview = d.to_ledger(), d.params_hash, preview(d.params)
        return d, entry

    @staticmethod
    def _execute(d: ActionDescriptor, execute: Callable[[dict[str, Any]], Any]) -> tuple[Any, ExecutionRecord]:
        t0 = time.perf_counter()
        started = datetime.now(UTC)
        try:
            result = execute(d.params)
        except Exception as e:
            rec = ExecutionRecord(status="failed", error=f"{type(e).__name__}: {e}"[:400], started_at=started,
                                  finished_at=datetime.now(UTC), duration_ms=int((time.perf_counter() - t0) * 1000))
            rec._exc = e  # type: ignore[attr-defined]
            return None, rec
        return result, ExecutionRecord(status="done", result_hash=_hash_or_none(result), result_preview=preview(result),
                                       started_at=started, finished_at=datetime.now(UTC),
                                       duration_ms=int((time.perf_counter() - t0) * 1000))

    @staticmethod
    async def _aexecute(d: ActionDescriptor, execute: Callable[[dict[str, Any]], Any]) -> tuple[Any, ExecutionRecord]:
        t0 = time.perf_counter()
        started = datetime.now(UTC)
        try:
            result = execute(d.params)
            if inspect.isawaitable(result):
                result = await result
        except Exception as e:
            rec = ExecutionRecord(status="failed", error=f"{type(e).__name__}: {e}"[:400], started_at=started,
                                  finished_at=datetime.now(UTC), duration_ms=int((time.perf_counter() - t0) * 1000))
            rec._exc = e  # type: ignore[attr-defined]
            return None, rec
        return result, ExecutionRecord(status="done", result_hash=_hash_or_none(result), result_preview=preview(result),
                                       started_at=started, finished_at=datetime.now(UTC),
                                       duration_ms=int((time.perf_counter() - t0) * 1000))


def entry_decision(entry: LedgerEntry) -> ConfirmDecision:
    c = entry.confirm
    return ConfirmDecision(c.status, c.approver, c.edits, c.note, channel=c.channel or "store",
                           decided_at=c.decided_at or datetime.now(UTC))


def _target(spec: Any, raw: dict[str, Any], det: Detection) -> str | None:
    if spec is None:
        return det.target
    if callable(spec):
        v = spec(raw)
        return None if v is None else str(v)
    if isinstance(spec, str) and spec in raw:
        v = raw[spec]
        return ", ".join(map(str, v)) if isinstance(v, (list, tuple)) else (None if v is None else str(v))
    return str(spec)


def _rebind(sig: inspect.Signature, raw: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Apply confirm-time edits to the arguments the function actually receives (JSON-able keys only)."""
    out = dict(raw)
    for k, v in params.items():
        if k in sig.parameters and k in out and _jsonable(out[k]) != v:
            out[k] = v
    return out


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if hasattr(obj, "model_dump"):
        return _jsonable(obj.model_dump())
    if hasattr(obj, "__dict__") and not callable(obj):
        return _jsonable({k: v for k, v in vars(obj).items() if not k.startswith("_")})
    return str(obj)


def _hash_or_none(result: Any) -> str | None:
    from attest.descriptor import short_hash
    return None if result is None else short_hash(_jsonable(result))


__all__ = ["Attest", "ActionReceipt", "AutoGate"]
