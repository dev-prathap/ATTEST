from __future__ import annotations

from typing import Any


class AttestError(Exception):
    """Base class."""


class ActionRefused(AttestError):
    """Policy said `refuse`. The action did not run. `reasons` explains why."""

    def __init__(self, action_id: str, reasons: list[str], descriptor: Any = None):
        self.action_id, self.reasons, self.descriptor = action_id, reasons, descriptor
        super().__init__(f"refused: {'; '.join(reasons)}")


class ActionRejected(AttestError):
    """A human rejected the confirm request. The action did not run."""

    def __init__(self, action_id: str, approver: str | None, note: str | None = None, descriptor: Any = None):
        self.action_id, self.approver, self.note, self.descriptor = action_id, approver, note, descriptor
        super().__init__(f"rejected by {approver or 'approver'}" + (f": {note}" if note else ""))


class ActionPending(AttestError):
    """Async gate modes (P1.3): the action is waiting; resume with `resume_token`."""

    def __init__(self, action_id: str, resume_token: str, descriptor: Any = None):
        self.action_id, self.resume_token, self.descriptor = action_id, resume_token, descriptor
        super().__init__(f"pending confirmation; resume_token={resume_token}")
