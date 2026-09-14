"""Gate: pause an `ask` decision until a human answers (doc 02 §2, doc 03 §6).

Modes (doc 03 §6), all behind one `Gate.confirm(request) -> ConfirmDecision` contract:
  sync-block        the gate blocks until a decision: ConsoleGate, StoreGate(wait=True) + Slack/web/webhook
  async-interrupt   InterruptGate — LangGraph `interrupt()`; the graph pauses, `Command(resume=…)` continues
  pending           StoreGate(wait=False) returns status "pending"; the caller gets ActionPending(resume_token)
                    and later calls `Attest.resume(token)`. Used by the MCP proxy and webhook UIs.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from attest.descriptor import ActionDescriptor, new_id


@dataclass
class ConfirmRequest:
    action_id: str
    descriptor: ActionDescriptor
    reasons: list[str]
    risk_tier: str
    approvers: list[str] = field(default_factory=list)
    hold: bool = False
    channel: str = "console"
    id: str = field(default_factory=lambda: new_id("cfm"))
    resume_token: str = field(default_factory=lambda: new_id("rsm"))
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    timeout_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = self.descriptor
        from attest.ledger.models import preview
        return {"id": self.id, "resume_token": self.resume_token, "action_id": self.action_id,
                "action": d.qualified_name, "system": d.system, "verb": d.verb, "target": d.target,
                "target_class": d.target_class, "agent": d.agent, "actor": d.actor, "run_id": d.run_id,
                "params_preview": preview(d.params), "params_hash": d.params_hash, "reasons": self.reasons,
                "risk_tier": self.risk_tier, "approvers": self.approvers, "hold": self.hold, "channel": self.channel,
                "requested_at": self.requested_at.isoformat()}


@dataclass
class ConfirmDecision:
    status: str  # approved | rejected | edited | pending | expired
    approver: str | None = None
    edits: dict[str, Any] | None = None
    note: str | None = None
    channel: str = "console"
    decided_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def approved(self) -> bool:
        return self.status in ("approved", "edited")

    @property
    def pending(self) -> bool:
        return self.status == "pending"

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "approver": self.approver, "edits": self.edits, "note": self.note,
                "channel": self.channel, "decided_at": self.decided_at.isoformat()}

    @classmethod
    def from_dict(cls, d: dict[str, Any] | str | bool | None, channel: str = "resume") -> ConfirmDecision:
        """Lenient parse of what a human/UI sends back: True/"approve"/{"status": "edited", "edits": {...}}."""
        if d is True or d in ("approve", "approved", "yes", "y", "ok"):
            return cls("approved", channel=channel)
        if d is False or d is None or d in ("reject", "rejected", "no", "n"):
            return cls("rejected", channel=channel)
        if isinstance(d, dict):
            status = str(d.get("status") or ("edited" if d.get("edits") else "approved")).lower()
            status = {"approve": "approved", "reject": "rejected", "edit": "edited"}.get(status, status)
            if status == "approved" and d.get("edits"):
                status = "edited"
            return cls(status, d.get("approver"), d.get("edits") or None, d.get("note"),
                       channel=d.get("channel") or channel)
        return cls("rejected", note=f"unparseable decision {d!r}", channel=channel)


class Gate(Protocol):
    name: str

    def confirm(self, request: ConfirmRequest) -> ConfirmDecision: ...

    async def aconfirm(self, request: ConfirmRequest) -> ConfirmDecision: ...


class AutoGate:
    """Deterministic gate for tests, CI and demos: always `decision`, optionally with edits."""

    name = "auto"

    def __init__(self, decision: str = "approved", *, approver: str = "auto", edits: dict[str, Any] | None = None):
        self.decision, self.approver, self.edits = decision, approver, edits
        self.requests: list[ConfirmRequest] = []

    def confirm(self, request: ConfirmRequest) -> ConfirmDecision:
        self.requests.append(request)
        status = "edited" if self.decision == "approved" and self.edits else self.decision
        return ConfirmDecision(status, self.approver, self.edits, channel=self.name)

    async def aconfirm(self, request: ConfirmRequest) -> ConfirmDecision:
        return self.confirm(request)


class Notifier(Protocol):
    """Something that tells humans about a pending request (Slack card, webhook POST, inbox URL)."""

    name: str

    def notify(self, request: ConfirmRequest, store: Any) -> None: ...


class StoreGate:
    """Persist the request, notify channels, then either block until decided (`wait=True`) or return
    `pending` so the caller resumes later (`wait=False`)."""

    name = "store"

    def __init__(self, store: Any = None, *, notifiers: list[Notifier] | None = None, wait: bool = True,
                 timeout_s: float | None = 900, poll_s: float = 0.5, ttl_s: float | None = 86400):
        from attest.gate.store import PendingStore
        self.store = store or PendingStore()
        self.notifiers = list(notifiers or [])
        self.wait, self.timeout_s, self.poll_s, self.ttl_s = wait, timeout_s, poll_s, ttl_s
        if self.notifiers:
            self.name = "+".join(n.name for n in self.notifiers)

    def confirm(self, request: ConfirmRequest) -> ConfirmDecision:
        request.channel = self.name
        self.store.create(request, ttl_s=self.ttl_s)
        for n in self.notifiers:
            try:
                n.notify(request, self.store)
            except Exception as e:  # a broken channel must not lose the request
                import logging
                logging.getLogger("attest.gate").warning("notifier %s failed: %s", n.name, e)
        if not self.wait:
            return ConfirmDecision("pending", channel=self.name)
        return self.store.wait(request.id, self.timeout_s, self.poll_s)

    async def aconfirm(self, request: ConfirmRequest) -> ConfirmDecision:
        import asyncio
        return await asyncio.to_thread(self.confirm, request)


def gate_from_env() -> Gate:
    """`ATTEST_AUTO_APPROVE=1` ⇒ approve everything (CI); `ATTEST_AUTO_APPROVE=0` ⇒ reject; else console."""
    from attest.gate.console import ConsoleGate
    v = os.environ.get("ATTEST_AUTO_APPROVE")
    if v is not None:
        return AutoGate("approved" if v.lower() in ("1", "true", "yes") else "rejected", approver="env")
    return ConsoleGate()


__all__ = ["ConfirmRequest", "ConfirmDecision", "Gate", "AutoGate", "Notifier", "StoreGate", "gate_from_env"]
