"""Gate: pause an `ask` decision until a human answers (doc 02 §2, doc 03 §6).

P1.1 ships the sync-block mode with a console channel and an auto gate for tests / CI.
Slack, web inbox, async-interrupt and MCP-pending arrive in P1.3 behind the same interface.
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


def gate_from_env() -> Gate:
    """`ATTEST_AUTO_APPROVE=1` ⇒ approve everything (CI); `ATTEST_AUTO_APPROVE=0` ⇒ reject; else console."""
    from attest.gate.console import ConsoleGate
    v = os.environ.get("ATTEST_AUTO_APPROVE")
    if v is not None:
        return AutoGate("approved" if v.lower() in ("1", "true", "yes") else "rejected", approver="env")
    return ConsoleGate()


__all__ = ["ConfirmRequest", "ConfirmDecision", "Gate", "AutoGate", "gate_from_env"]
