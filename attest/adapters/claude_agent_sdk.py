"""Claude Agent SDK adapter — Attest as PreToolUse / PostToolUse hooks.

    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher
    from attest.adapters import claude_agent_sdk as attest_cl

    mapping = {"mcp__gmail__send_message": {"system": "gmail", "verb": "send", "target": "to"}}
    pre, post = attest_cl.hooks(at, mapping=mapping)
    options = ClaudeAgentOptions(hooks={"PreToolUse": [HookMatcher(hooks=[pre])],
                                        "PostToolUse": [HookMatcher(hooks=[post])]})

PreToolUse decides + gates: refuse / rejected ⇒ `permissionDecision: "deny"` with the reason; approved ⇒ "allow"
(with `updatedInput` when the human edited params). PostToolUse verifies the tool response and writes the
ledger row. The pending row is written at PreToolUse so a denied or crashed call still leaves a record.
Hook inputs are plain dicts (`tool_name`, `tool_input`, `tool_response`, `session_id`, `tool_use_id`), so the
adapter has no import of the SDK and can be driven by tests.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from attest.adapters.langgraph import Mapping, descriptor_for
from attest.core import Attest, entry_decision
from attest.descriptor import ActionDescriptor, short_hash
from attest.exceptions import ActionPending, ActionRefused, ActionRejected
from attest.ledger import ConfirmRecord, ExecutionRecord, LedgerEntry
from attest.ledger.models import VerificationRecord, preview
from attest.verify import verify


class _Parked:
    def __init__(self, d: ActionDescriptor, entry: LedgerEntry, spec: dict[str, Any]):
        self.d, self.entry, self.spec = d, entry, spec


def hooks(client: Attest | None = None, *, mapping: Mapping | None = None, server: str | None = None
          ) -> tuple[Callable[..., Any], Callable[..., Any]]:
    """→ (pre_tool_use, post_tool_use) async hook callables with the SDK's `(input, tool_use_id, context)` shape."""
    at = client or __import__("attest").default()
    parked: dict[str, _Parked] = {}

    async def pre_tool_use(input_data: dict[str, Any], tool_use_id: str | None = None,
                           context: Any = None) -> dict[str, Any]:
        name = str(input_data.get("tool_name") or "")
        args = dict(input_data.get("tool_input") or {})
        srv = server or (name.split("__")[1] if name.startswith("mcp__") and name.count("__") >= 2 else None)
        d, recognised, spec = descriptor_for(at, name, args, mapping, server=srv)
        d.extra["framework"] = "claude-agent-sdk"
        d.run_id = d.run_id or input_data.get("session_id")
        pol = at.policy.evaluate(d, recognised=recognised)
        d.target_class = pol.target_class  # type: ignore[assignment]
        entry = at._entry(d, pol)
        key = tool_use_id or d.id
        if pol.decision == "refuse":
            at.ledger.append(entry)
            return _deny(f"attest refused: {'; '.join(pol.reasons)}")
        updated: dict[str, Any] | None = None
        if pol.decision == "ask":
            request = at._request(d, pol)
            decision = at.gate.confirm(request)
            if decision.pending:
                try:
                    at._park(d, entry, request, decision, lambda p: None, spec.get("verify"), spec.get("readers"),
                             spec.get("http_get"))
                except ActionPending as e:
                    return _deny(f"attest: pending human confirmation (resume_token={e.resume_token}); retry later")
            try:
                d, entry = at._after_confirm(d, entry, decision)
            except ActionRejected as e:
                return _deny("attest: a human rejected this action" + (f" ({e.note})" if e.note else ""))
            if decision.edits:
                updated = {**args, **{k: v for k, v in d.params.items() if k in args}}
        parked[key] = _Parked(d, entry, spec)
        reason = "attest: " + ("; ".join(pol.reasons) or pol.decision)
        out: dict[str, Any] = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                                      "permissionDecisionReason": reason}}
        if updated is not None:
            out["hookSpecificOutput"]["updatedInput"] = updated
        return out

    async def post_tool_use(input_data: dict[str, Any], tool_use_id: str | None = None,
                            context: Any = None) -> dict[str, Any]:
        name = str(input_data.get("tool_name") or "")
        key = tool_use_id or ""
        parked_item = parked.pop(key, None)
        if parked_item is None:  # PostToolUse without our PreToolUse (hook not matched) — record what we can
            args = dict(input_data.get("tool_input") or {})
            d, recognised, spec = descriptor_for(at, name, args, mapping, server=server)
            pol = at.policy.evaluate(d, recognised=recognised)
            entry = at._entry(d, pol)
            entry.confirm = ConfirmRecord(status="not_required")
        else:
            d, entry, spec = parked_item.d, parked_item.entry, parked_item.spec
        response = input_data.get("tool_response")
        result = _unwrap(response)
        failed = isinstance(response, dict) and (response.get("is_error") or response.get("isError"))
        entry.execution = ExecutionRecord(status="failed" if failed else "done",
                                          result_hash=None if result is None else short_hash(result),
                                          result_preview=preview(result), error=str(result)[:400] if failed else None)
        if failed:
            entry.verification = VerificationRecord(level="attested-only", method="none",
                                                    evidence={"detail": "tool error"})
        else:
            entry.verification = verify(d.with_result(result), result, custom=spec.get("verify"),
                                        drivers=at._drivers(spec.get("readers"), spec.get("http_get")))
        at.ledger.append(entry)
        return {}

    return pre_tool_use, post_tool_use


def _deny(reason: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def _unwrap(response: Any) -> Any:
    """Tool responses arrive as MCP-style content lists or plain values; pull out something the ladder can judge."""
    if isinstance(response, dict) and isinstance(response.get("content"), list):
        import json
        texts = [c.get("text", "") for c in response["content"] if isinstance(c, dict) and c.get("type") == "text"]
        joined = "\n".join(texts).strip()
        try:
            return json.loads(joined) if joined else response
        except json.JSONDecodeError:
            return joined or response
    return response


__all__ = ["hooks"]
_ = (ActionRefused, entry_decision)
