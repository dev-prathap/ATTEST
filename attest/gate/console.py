"""Console gate — y / n / e(dit) on the terminal. A non-interactive stdin rejects (never silently approves)."""
from __future__ import annotations

import asyncio
import getpass
import json
import sys
from typing import Any, TextIO

from attest.gate import ConfirmDecision, ConfirmRequest
from attest.ledger.models import preview


class ConsoleGate:
    name = "console"

    def __init__(self, *, stdin: TextIO | None = None, stdout: TextIO | None = None, approver: str | None = None):
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.approver = approver

    def _render(self, r: ConfirmRequest) -> str:
        d = r.descriptor
        lines = [
            "",
            "┌─ attest: confirmation required ─────────────────────────────",
            f"│ action   {d.qualified_name}   risk={r.risk_tier}   target={d.target_class}",
            f"│ agent    {d.agent or '-'}   actor={d.actor or '-'}   run={d.run_id or '-'}",
            f"│ params   {json.dumps(preview(d.params), default=str)}   hash={d.params_hash}",
        ]
        for reason in r.reasons:
            lines.append(f"│ why      {reason}")
        if r.approvers:
            lines.append(f"│ approvers {', '.join(r.approvers)}")
        prompt = "fix params and retry" if r.hold else "approve"
        lines.append(f"└─ [y] {prompt}   [n] reject   [e] edit params as JSON   ")
        return "\n".join(lines)

    def confirm(self, request: ConfirmRequest) -> ConfirmDecision:
        who = self.approver or getpass.getuser()
        if not _interactive(self.stdin):
            return ConfirmDecision("rejected", who, note="non-interactive stdin: rejected by default",
                                   channel=self.name)
        self.stdout.write(self._render(request) + "\n")
        self.stdout.flush()
        while True:
            self.stdout.write("attest> ")
            self.stdout.flush()
            ans = (self.stdin.readline() or "").strip().lower()
            if ans in ("y", "yes"):
                return ConfirmDecision("approved", who, channel=self.name)
            if ans in ("n", "no", ""):
                return ConfirmDecision("rejected", who, channel=self.name)
            if ans in ("e", "edit"):
                self.stdout.write("new params (JSON object, merged over the current ones): ")
                self.stdout.flush()
                raw = self.stdin.readline()
                try:
                    edits: dict[str, Any] = json.loads(raw)
                    if not isinstance(edits, dict):
                        raise ValueError("not an object")
                except Exception as e:
                    self.stdout.write(f"  invalid JSON ({e}); try again\n")
                    continue
                return ConfirmDecision("edited", who, edits, channel=self.name)
            self.stdout.write("  answer y, n or e\n")

    async def aconfirm(self, request: ConfirmRequest) -> ConfirmDecision:
        return await asyncio.to_thread(self.confirm, request)


def _interactive(stream: TextIO) -> bool:
    try:
        return stream.isatty() or getattr(stream, "_attest_force_interactive", False)
    except Exception:
        return False
