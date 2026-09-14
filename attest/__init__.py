"""Attest — proof layer for AI agents. Decide → Gate → Verify → Attest.

    import attest

    @attest.action(system="gmail", verb="send", target="to")
    def send_email(to, subject, body): ...

Module-level `action`, `attest`, `run` use a lazily created default client (ledger at
`.attest/ledger.sqlite` or `$ATTEST_LEDGER`, policy from `$ATTEST_POLICY` / `./attest.yaml`, console gate).
"""
from __future__ import annotations

from typing import Any

from attest.core import ActionReceipt, Attest
from attest.descriptor import ActionDescriptor
from attest.exceptions import ActionPending, ActionRefused, ActionRejected, AttestError
from attest.gate import AutoGate, ConfirmDecision, ConfirmRequest, StoreGate
from attest.gate.console import ConsoleGate
from attest.gate.store import PendingStore
from attest.ledger import LedgerEntry, SqliteLedger
from attest.policy import PolicyContext, PolicyEngine, PolicyResult
from attest.registry import Detection, detect, register
from attest.verify import Level, ReadBackDriver

__version__ = "0.1.0"
_default: Attest | None = None


def default() -> Attest:
    global _default
    if _default is None:
        _default = Attest()
    return _default


def configure(**kw: Any) -> Attest:
    """Replace the default client (e.g. `attest.configure(agent="x", gate=AutoGate())`)."""
    global _default
    _default = Attest(**kw)
    return _default


def action(fn=None, **kw):
    return default().action(fn, **kw)


def attest(**kw):  # noqa: A001 - module-level verb by design
    return default().attest(**kw)


def run(run_id: str | None = None, **kw):
    return default().run(run_id, **kw)


__all__ = ["Attest", "ActionReceipt", "ActionDescriptor", "ActionRefused", "ActionRejected", "ActionPending",
           "AttestError", "AutoGate", "ConsoleGate", "StoreGate", "PendingStore", "ConfirmDecision", "ConfirmRequest",
           "LedgerEntry", "SqliteLedger",
           "PolicyContext", "PolicyEngine", "PolicyResult", "Detection", "detect", "register", "Level",
           "ReadBackDriver",
           "action", "attest", "run", "default", "configure", "__version__"]
