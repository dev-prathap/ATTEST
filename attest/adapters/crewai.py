"""CrewAI adapter — wraps `crewai.tools.BaseTool` instances (or anything with `name`, `description`, `_run`).

    from attest.adapters import crewai as attest_crew
    tools = attest_crew.wrap_tools([send_email_tool, update_deal_tool], at, mapping={...})
    agent = Agent(role="…", tools=tools)

Returns a subclass instance of the original tool whose `_run` (and `_arun` when present) goes through
decide → gate → execute → verify → attest. Refusals / rejections return an error string to the agent.
"""
from __future__ import annotations

from typing import Any

from attest.adapters.langgraph import Mapping, _error_text, _only_known, descriptor_for
from attest.core import Attest
from attest.exceptions import ActionPending, ActionRefused, ActionRejected


def wrap_tool(tool: Any, client: Attest | None = None, *, mapping: Mapping | None = None,
              raise_on_block: bool = False) -> Any:
    at = client or __import__("attest").default()
    name = getattr(tool, "name", type(tool).__name__)
    spec = dict((mapping or {}).get(name) or {})
    orig_run = tool._run
    orig_arun = getattr(tool, "_arun", None)

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        params, by_name = _params(orig_run, args, kwargs)
        d, recognised, sp = descriptor_for(at, name, params, mapping)
        d.extra["framework"] = "crewai"
        call = (lambda p: orig_run(**{**params, **_only_known(params, p)})) if by_name else \
            (lambda p: orig_run(*args, **{**kwargs, **_only_known(kwargs, p)}))
        try:
            receipt = at.run_action(d, call, recognised=recognised, verify_fn=sp.get("verify"),
                                    readers=sp.get("readers"), http_get=sp.get("http_get"))
        except ActionPending as e:
            if raise_on_block:
                raise
            return f"attest: pending human confirmation (resume_token={e.resume_token})"
        except (ActionRefused, ActionRejected) as e:
            if raise_on_block:
                raise
            return _error_text(e)
        return receipt.result

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        target = orig_arun or orig_run
        params, by_name = _params(target, args, kwargs)
        d, recognised, sp = descriptor_for(at, name, params, mapping)
        d.extra["framework"] = "crewai"
        call = (lambda p: target(**{**params, **_only_known(params, p)})) if by_name else \
            (lambda p: target(*args, **{**kwargs, **_only_known(kwargs, p)}))
        try:
            receipt = await at.arun_action(d, call, recognised=recognised, verify_fn=sp.get("verify"),
                                           readers=sp.get("readers"), http_get=sp.get("http_get"))
        except ActionPending as e:
            if raise_on_block:
                raise
            return f"attest: pending human confirmation (resume_token={e.resume_token})"
        except (ActionRefused, ActionRejected) as e:
            if raise_on_block:
                raise
            return _error_text(e)
        return receipt.result

    cls = type(tool)
    wrapped_cls = type(f"Attested{cls.__name__}", (cls,), {"_run": _run, "_arun": _arun, "_attest_wrapped": True})
    try:  # pydantic models (crewai BaseTool) — copy fields
        wrapped = wrapped_cls.model_validate(tool.model_dump()) if hasattr(tool, "model_dump") else None
    except Exception:
        wrapped = None
    if wrapped is None:
        import copy
        wrapped = copy.copy(tool)
        wrapped.__class__ = wrapped_cls
    _ = spec
    return wrapped


def _params(fn: Any, args: tuple, kwargs: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """→ (params, by_name): positional args mapped onto the function's parameter names when possible."""
    if not args:
        return dict(kwargs), True
    import inspect
    try:
        names = [p for p in inspect.signature(fn).parameters if p not in ("self", "args", "kwargs")]
    except (TypeError, ValueError):
        names = []
    by_name = len(names) >= len(args)
    out = {names[i] if i < len(names) else f"arg{i}": a for i, a in enumerate(args)}
    out.update(kwargs)
    return out, by_name


def wrap_tools(tools: list[Any], client: Attest | None = None, *, mapping: Mapping | None = None,
               raise_on_block: bool = False) -> list[Any]:
    return [wrap_tool(t, client, mapping=mapping, raise_on_block=raise_on_block) for t in tools]


__all__ = ["wrap_tool", "wrap_tools"]
