"""OpenAI Agents SDK adapter — wraps `FunctionTool`s so every call runs decide → gate → execute → verify → attest.

    from agents import Agent, function_tool
    from attest.adapters import openai_agents as attest_oa

    tools = attest_oa.wrap_tools([send_email, update_deal], at, mapping={
        "send_email": {"system": "gmail", "verb": "send", "target": "to"},
    })
    agent = Agent(name="followup", tools=tools)

HITL: with a blocking gate the call waits; with `StoreGate(wait=False)` (pending mode) the tool returns
`{"status": "pending_confirmation", "resume_token": …}` to the model and your app later calls
`attest_oa.resume(at, token)` (or `at.resume(token)`) to execute once a human approved.
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any

from attest.adapters.langgraph import Mapping, _error_text, _only_known, descriptor_for
from attest.core import Attest
from attest.exceptions import ActionPending, ActionRefused, ActionRejected


def _default(client: Attest | None) -> Attest:
    if client is not None:
        return client
    import attest
    return attest.default()


def wrap_tool(tool: Any, client: Attest | None = None, *, mapping: Mapping | None = None,
              raise_on_block: bool = False) -> Any:
    """`tool` is an `agents.FunctionTool` (or anything with name / on_invoke_tool(ctx, input_json))."""
    at = _default(client)
    name, orig = tool.name, tool.on_invoke_tool
    spec = dict((mapping or {}).get(name) or {})

    async def on_invoke_tool(ctx: Any, input_json: str) -> Any:
        try:
            args = json.loads(input_json) if input_json else {}
        except json.JSONDecodeError:
            args = {"input": input_json}
        if not isinstance(args, dict):
            args = {"input": args}
        d, recognised, sp = descriptor_for(at, name, args, mapping)
        d.extra["framework"] = "openai-agents"

        async def execute(p: dict[str, Any]) -> Any:
            merged = {**args, **_only_known(args, p)}
            return await orig(ctx, json.dumps(merged))

        try:
            receipt = await at.arun_action(d, execute, recognised=recognised, verify_fn=sp.get("verify"),
                                           readers=sp.get("readers"), http_get=sp.get("http_get"))
        except ActionPending as e:
            if raise_on_block:
                raise
            return json.dumps({"status": "pending_confirmation", "resume_token": e.resume_token,
                               "message": "A human must approve this action; call back once approved."})
        except (ActionRefused, ActionRejected) as e:
            if raise_on_block:
                raise
            return _error_text(e)
        return receipt.result

    _ = spec
    if dataclasses.is_dataclass(tool):
        wrapped = dataclasses.replace(tool, on_invoke_tool=on_invoke_tool)
    else:  # duck-typed object: shallow copy with the new invoker
        import copy
        wrapped = copy.copy(tool)
        wrapped.on_invoke_tool = on_invoke_tool
    try:
        wrapped._attest_wrapped = True  # type: ignore[attr-defined]
    except Exception:
        pass
    return wrapped


def wrap_tools(tools: list[Any], client: Attest | None = None, *, mapping: Mapping | None = None,
               raise_on_block: bool = False) -> list[Any]:
    return [wrap_tool(t, client, mapping=mapping, raise_on_block=raise_on_block) for t in tools]


async def resume(client: Attest, resume_token: str) -> Any:
    """Execute a parked tool call after approval (same process). Returns the tool's result."""
    return (await client.aresume(resume_token)).result


__all__ = ["wrap_tool", "wrap_tools", "resume"]
