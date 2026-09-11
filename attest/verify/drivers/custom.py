"""L2 — the customer's own check. Signature: `verify(result)` or `verify(result, descriptor)`; may be async;
returns truthy / falsy, or `(bool, evidence_dict)`. Falsy ⇒ `unverified`; raising ⇒ degraded, not unverified."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from attest.descriptor import ActionDescriptor
from attest.ledger.models import VerificationRecord


def run(fn: Callable[..., Any], result: Any, descriptor: ActionDescriptor) -> VerificationRecord:
    from attest.verify.ladder import _custom_sync
    return _custom_sync(fn, result, descriptor)


async def arun(fn: Callable[..., Any], result: Any, descriptor: ActionDescriptor) -> VerificationRecord:
    from attest.verify.ladder import _custom_async
    return await _custom_async(fn, result, descriptor)
