"""LangGraph / LangChain adapter — every tool goes through decide → gate → execute → verify → attest.

    from attest.adapters import langgraph as attest_lg

    tools = attest_lg.wrap_tools([send_email, update_deal], client=at, mapping={
        "send_email": {"system": "gmail", "verb": "send", "target": "to"},
        "update_deal": {"system": "hubspot", "verb": "update", "target": "deal_id"},
    })
    graph = create_react_agent(model, tools)                 # or …
    graph = attest_lg.wrap(graph, client=at, mapping=…)      # patch the ToolNode(s) of an existing graph
    agent = create_agent(model, tools, middleware=[attest_lg.AttestMiddleware(at, mapping=…)])   # langchain ≥ 1

Refusals and rejections come back to the model as an error ToolMessage (the run continues; the agent can
explain or try something else). The ledger records the decision either way.

Pattern from DeerFlow `ToolReceiptMiddleware`: wrap the tool call at the outermost layer so nothing
downstream can short-circuit the record.
"""
from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from typing import Any

from attest.core import Attest
from attest.descriptor import ActionDescriptor
from attest.exceptions import ActionRefused, ActionRejected
from attest.registry import detect

Mapping = dict[str, dict[str, Any]]


def _default_client(client: Attest | None) -> Attest:
    if client is not None:
        return client
    import attest
    return attest.default()


def _spec(mapping: Mapping | None, name: str) -> dict[str, Any]:
    return dict((mapping or {}).get(name) or {})


def descriptor_for(client: Attest, name: str, args: dict[str, Any], mapping: Mapping | None,
                   server: str | None = None) -> tuple[ActionDescriptor, bool, dict[str, Any]]:
    """Build the descriptor for one tool call. Returns (descriptor, recognised, spec)."""
    from attest.core import _current_actor, _current_run, _jsonable, _target
    spec = _spec(mapping, name)
    det = detect(system=spec.get("system"), verb=spec.get("verb"), target=None, tool_name=name, server=server)
    d = ActionDescriptor(system=det.system, verb=det.verb, target=_target(spec.get("target"), args, det),
                         params=_jsonable(args), actor=_current_actor.get() or client.actor, agent=client.agent,
                         run_id=_current_run.get(), risk=spec.get("risk"), source=det.source,
                         extra={"tool_name": name, **({"framework": "langgraph"})})
    return d, det.recognised, spec


def _error_text(e: Exception) -> str:
    if isinstance(e, ActionRefused):
        return f"attest refused this action: {'; '.join(e.reasons)}"
    if isinstance(e, ActionRejected):
        return "attest: a human rejected this action" + (f" ({e.note})" if e.note else "")
    return f"attest: {e}"


# ── tool wrapping ─────────────────────────────────────────────────────────────
def wrap_tool(tool: Any, client: Attest | None = None, *, mapping: Mapping | None = None,
              raise_on_block: bool = False) -> Any:
    """Return a copy of a LangChain tool whose execution runs through Attest. Works for `StructuredTool`
    (what `@tool` makes) by swapping `func`/`coroutine`; any other BaseTool is delegated to via `invoke`."""
    from langchain_core.tools import StructuredTool

    at = _default_client(client)
    name = tool.name
    spec = _spec(mapping, name)

    def run_sync(kwargs: dict[str, Any], call: Callable[..., Any]) -> Any:
        d, recognised, sp = descriptor_for(at, name, kwargs, mapping)
        try:
            receipt = at.run_action(d, lambda p: call(**{**kwargs, **_only_known(kwargs, p)}), recognised=recognised,
                                    verify_fn=sp.get("verify"), readers=sp.get("readers"), http_get=sp.get("http_get"))
        except (ActionRefused, ActionRejected) as e:
            if raise_on_block:
                raise
            return _error_text(e)
        return receipt.result

    async def run_async(kwargs: dict[str, Any], call: Callable[..., Any]) -> Any:
        d, recognised, sp = descriptor_for(at, name, kwargs, mapping)
        try:
            receipt = await at.arun_action(d, lambda p: call(**{**kwargs, **_only_known(kwargs, p)}),
                                           recognised=recognised, verify_fn=sp.get("verify"), readers=sp.get("readers"),
                                           http_get=sp.get("http_get"))
        except (ActionRefused, ActionRejected) as e:
            if raise_on_block:
                raise
            return _error_text(e)
        return receipt.result

    if isinstance(tool, StructuredTool) and (tool.func is not None or tool.coroutine is not None):
        orig_func, orig_coro = tool.func, tool.coroutine

        def func(**kwargs: Any) -> Any:
            if orig_func is None:  # sync call on an async-only tool: run the coroutine
                import asyncio
                return asyncio.run(run_async(kwargs, orig_coro))
            return run_sync(kwargs, orig_func)

        async def coroutine(**kwargs: Any) -> Any:
            if orig_coro is None:
                return run_sync(kwargs, orig_func)
            return await run_async(kwargs, orig_coro)

        wrapped = tool.model_copy(update={"func": func, "coroutine": coroutine})
        wrapped.__dict__["_attest_wrapped"] = True
        return wrapped

    # generic BaseTool: delegate through invoke / ainvoke
    def func2(**kwargs: Any) -> Any:
        return run_sync(kwargs, lambda **kw: tool.invoke(kw))

    async def coroutine2(**kwargs: Any) -> Any:
        return await run_async(kwargs, lambda **kw: tool.ainvoke(kw))

    wrapped = StructuredTool.from_function(func=func2, coroutine=coroutine2, name=name, description=tool.description,
                                           args_schema=tool.args_schema,
                                           return_direct=getattr(tool, "return_direct", False))
    wrapped.__dict__["_attest_wrapped"] = True
    _ = spec
    return wrapped


def _only_known(kwargs: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Confirm-time edits: only keys the tool was called with may change."""
    return {k: v for k, v in params.items() if k in kwargs}


def wrap_tools(tools: list[Any], client: Attest | None = None, *, mapping: Mapping | None = None,
               raise_on_block: bool = False) -> list[Any]:
    return [wrap_tool(t, client, mapping=mapping, raise_on_block=raise_on_block) for t in tools]


# ── graph patching ────────────────────────────────────────────────────────────
def wrap(graph: Any, client: Attest | None = None, *, mapping: Mapping | None = None,
         raise_on_block: bool = False) -> Any:
    """Patch every ToolNode in a compiled or uncompiled LangGraph graph in place; returns the graph."""
    from langgraph.prebuilt import ToolNode

    patched = 0
    for node in getattr(graph, "nodes", {}).values():
        runnable = getattr(node, "bound", None) or getattr(node, "runnable", None) or node
        if isinstance(runnable, ToolNode):
            _patch_tool_node(runnable, client, mapping, raise_on_block)
            patched += 1
    if patched == 0:
        raise ValueError("attest.adapters.langgraph.wrap: no ToolNode found in graph.nodes — "
                         "wrap the tools with wrap_tools() before building the graph instead")
    graph.__dict__["_attest_patched_nodes"] = patched
    return graph


def _patch_tool_node(node: Any, client: Attest | None, mapping: Mapping | None, raise_on_block: bool) -> None:
    store = getattr(node, "_tools_by_name", None)
    if store is None:
        store = getattr(node, "tools_by_name", None)
    if not isinstance(store, dict):
        raise ValueError("unsupported ToolNode layout: no tools_by_name")
    for name, t in list(store.items()):
        if getattr(t, "_attest_wrapped", False) or t.__dict__.get("_attest_wrapped"):
            continue
        store[name] = wrap_tool(t, client, mapping=mapping, raise_on_block=raise_on_block)


# ── langchain ≥ 1 middleware ──────────────────────────────────────────────────
def _tool_message(content: str, tool_call_id: str, name: str, status: str = "error") -> Any:
    from langchain_core.messages import ToolMessage
    return ToolMessage(content=content, tool_call_id=tool_call_id, name=name, status=status)


def _result_of(message: Any) -> Any:
    """Turn a ToolMessage into something the ack driver can judge: parsed JSON content, or the raw string."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        try:
            return json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return content or None
    return content


try:  # langchain ≥ 1.0 only
    from langchain.agents.middleware import AgentMiddleware as _AgentMiddleware
except Exception:  # pragma: no cover - optional
    _AgentMiddleware = object  # type: ignore[misc,assignment]


class AttestMiddleware(_AgentMiddleware):  # type: ignore[misc]
    """`create_agent(model, tools, middleware=[AttestMiddleware(at, mapping=…)])`.

    Place it first so it is the outermost tool-call layer (DeerFlow ordering rule)."""

    def __init__(self, client: Attest | None = None, *, mapping: Mapping | None = None):
        if _AgentMiddleware is not object:
            super().__init__()
        self.client, self.mapping = client, mapping

    def _run(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        at = _default_client(self.client)
        call = request.tool_call
        name, args, call_id = call.get("name", ""), dict(call.get("args") or {}), str(call.get("id") or "")
        d, recognised, sp = descriptor_for(at, name, args, self.mapping)
        box: dict[str, Any] = {}

        def execute(p: dict[str, Any]) -> Any:
            req = request
            if p != d.params:
                req = request.override(tool_call={**call, "args": {**args, **_only_known(args, p)}}) \
                    if hasattr(request, "override") else request
            box["msg"] = handler(req)
            if inspect.isawaitable(box["msg"]):
                return box["msg"]
            return _result_of(box["msg"])

        try:
            at.run_action(d, execute, recognised=recognised, verify_fn=sp.get("verify"), readers=sp.get("readers"),
                          http_get=sp.get("http_get"))
        except (ActionRefused, ActionRejected) as e:
            return _tool_message(_error_text(e), call_id, name)
        return box["msg"]

    async def _arun(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        at = _default_client(self.client)
        call = request.tool_call
        name, args, call_id = call.get("name", ""), dict(call.get("args") or {}), str(call.get("id") or "")
        d, recognised, sp = descriptor_for(at, name, args, self.mapping)
        box: dict[str, Any] = {}

        async def execute(p: dict[str, Any]) -> Any:
            req = request
            if p != d.params and hasattr(request, "override"):
                req = request.override(tool_call={**call, "args": {**args, **_only_known(args, p)}})
            box["msg"] = await handler(req)
            return _result_of(box["msg"])

        try:
            await at.arun_action(d, execute, recognised=recognised, verify_fn=sp.get("verify"),
                                 readers=sp.get("readers"), http_get=sp.get("http_get"))
        except (ActionRefused, ActionRejected) as e:
            return _tool_message(_error_text(e), call_id, name)
        return box["msg"]

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return self._run(request, handler)

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return await self._arun(request, handler)


__all__ = ["wrap", "wrap_tool", "wrap_tools", "AttestMiddleware", "descriptor_for"]
