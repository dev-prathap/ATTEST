"""Recipe registry entry point: infer `system` / `verb` / `target` from whatever the caller has —
an MCP tool name, an HTTP method + URL, an SDK call path, or a plain function name. Customers can
register overrides; explicit arguments always win.
"""
from __future__ import annotations

from dataclasses import dataclass

from attest.registry import mcp_names, sdk_names, url_patterns
from attest.registry.systems import canonical_system
from attest.registry.verbs import classify, is_write, risk_for

__all__ = ["Detection", "detect", "register", "risk_for", "is_write", "classify"]


@dataclass(frozen=True)
class Detection:
    system: str
    verb: str
    target: str | None
    source: str  # manual | mcp | url | sdk | heuristic
    recognised: bool

    @property
    def action_id(self) -> str:
        return f"{self.system}_{self.verb}" + (f"_{self.target}" if self.target else "")


_OVERRIDES: dict[str, tuple[str, str]] = {}


def register(name: str, *, system: str, verb: str) -> None:
    """Customer override: an exact tool / function / `METHOD url` string → (system, verb)."""
    _OVERRIDES[name] = (system, verb)


def detect(
    *,
    system: str | None = None,
    verb: str | None = None,
    target: str | None = None,
    tool_name: str | None = None,
    server: str | None = None,
    method: str | None = None,
    url: str | None = None,
    sdk_path: str | None = None,
    function_name: str | None = None,
) -> Detection:
    """Explicit `system`/`verb` win. Then MCP tool name, then method+URL, then SDK path, then the
    function name as a last-resort heuristic. Anything left over is `unknown` / `write`."""
    key = tool_name or (f"{(method or 'GET').upper()} {url}" if url else None) or sdk_path or function_name
    if key and key in _OVERRIDES:
        s, v = _OVERRIDES[key]
        return Detection(system or s, verb or v, target, "manual", True)

    d_system, d_verb, d_target, source, recognised = "unknown", "write", None, "heuristic", False
    if tool_name:
        d_system, d_verb, d_target, recognised = mcp_names.detect(tool_name, server=server)
        source = "mcp"
    elif url:
        d_system, d_verb, d_target, recognised = url_patterns.detect(method or "GET", url)
        source = "url"
    elif sdk_path:
        d_system, d_verb, d_target, recognised = sdk_names.detect(sdk_path)
        source = "sdk"
    elif function_name:
        d_system, d_verb, d_target, recognised = sdk_names.detect(function_name)
        source = "heuristic"

    final_system = canonical_system(system) or system or d_system
    final_verb = verb or d_verb
    if system and verb:
        source = "manual"
    return Detection(final_system, final_verb, target or d_target, source, recognised or bool(verb))
