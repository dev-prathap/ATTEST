"""Recipe proposals (P3.4): derive read-back pairs from an OpenAPI spec or an MCP `tools/list`, then (optionally)
ask a model which fields to compare. Output is a JSON proposal for a human to review and `attest recipes install`.

    attest recipes propose --openapi spec.yaml --system someweirdcrm [--llm]
    attest recipes propose --mcp-tools tools.json --system tracker [--llm]
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from attest.verify.drivers.openapi import _PARAM, _load

_ID = re.compile(r"id$", re.I)


def from_openapi(spec: Any, system: str) -> list[dict[str, Any]]:
    doc = _load(spec)
    base = ((doc.get("servers") or [{}])[0].get("url") or "").rstrip("/")
    paths = doc.get("paths") or {}
    out: list[dict[str, Any]] = []
    for path, ops in paths.items():
        if not isinstance(ops, dict):
            continue
        methods = {m.lower() for m in ops if m.lower() in ("post", "put", "patch")}
        if not methods:
            continue
        # create: POST /x ⇒ GET /x/{id}; update: PUT/PATCH /x/{id} ⇒ GET same
        candidates: list[tuple[str, str, list[str]]] = []
        if "post" in methods:
            for tpl, tops in paths.items():
                if isinstance(tops, dict) and "get" in {m.lower() for m in tops} and tpl.rsplit("/", 1)[0] == path and _PARAM.findall(tpl):
                    candidates.append((tpl, "create", ["create"]))
        if methods & {"put", "patch"} and "get" in {m.lower() for m in ops}:
            candidates.append((path, "update", ["update"]))
        for tpl, kind, verbs in candidates:
            last = _PARAM.findall(tpl)[-1]
            resource = [s for s in path.split("/") if s and not _PARAM.match(s)][-1] if [s for s in path.split("/") if s and not _PARAM.match(s)] else "record"
            fields = _response_fields(ops, paths.get(tpl, {}))
            out.append({
                "name": f"{system}.{resource.rstrip('s')}.{kind}", "system": system, "verbs": verbs, "target": resource.rstrip("s"),
                "read": {"method": "GET", "url": base + tpl.replace("{" + last + "}", "{id}"),
                         "id": "$.id" if kind == "create" else f"$params.{last}|$.id"},
                "compare": {"fields": fields, "exists": True}, "source": "openapi", "version": 1,
                "review": "check `compare.fields` are the writable properties the read returns unchanged",
            })
    return out


def _response_fields(write_ops: dict[str, Any], read_ops: dict[str, Any]) -> list[str] | None:
    """Intersection of the write request body properties and the read response properties, when both are declared."""
    def props(schema: Any) -> set[str]:
        if not isinstance(schema, dict):
            return set()
        if "properties" in schema:
            return set(schema["properties"].keys())
        for k in ("allOf", "oneOf", "anyOf"):
            if k in schema:
                return set().union(*(props(s) for s in schema[k]))
        return set()
    body = set()
    for m in ("post", "put", "patch"):
        content = ((write_ops.get(m) or {}).get("requestBody") or {}).get("content") or {}
        for c in content.values():
            body |= props(c.get("schema"))
    resp = set()
    for code, r in ((read_ops.get("get") or {}).get("responses") or {}).items():
        if str(code).startswith("2"):
            for c in (r.get("content") or {}).values():
                resp |= props(c.get("schema"))
    both = sorted(body & resp - {"id"})
    return both or None


def from_mcp_tools(tools: list[dict[str, Any]], system: str) -> list[dict[str, Any]]:
    by_name = {t["name"]: t for t in tools}
    out = []
    for t in tools:
        name = t["name"]
        toks = name.replace("-", "_").split("_")
        if toks[0] not in ("create", "update", "add", "upsert") or len(toks) < 2:
            continue
        rest = "_".join(toks[1:])
        getter = next((by_name.get(g) for g in (f"get_{rest}", f"fetch_{rest}", f"read_{rest}", f"retrieve_{rest}") if by_name.get(g)), None)
        if not getter:
            continue
        req = list((getter.get("inputSchema") or {}).get("required") or [])
        if len(req) != 1 or not _ID.search(req[0]):
            continue
        write_props = set(((t.get("inputSchema") or {}).get("properties") or {}).keys())
        out.append({
            "name": f"{system}.{rest}.{'create' if toks[0] != 'update' else 'update'}", "system": system,
            "verbs": ["create"] if toks[0] != "update" else ["update"], "target": rest,
            "read": {"mcp_tool": getter["name"], "id_arg": req[0], "id": "$.id" if toks[0] != "update" else f"$params.{req[0]}|$.id"},
            "compare": {"fields": sorted(write_props - {req[0]}) or None, "exists": True},
            "source": "mcp", "version": 1, "review": f"confirm {getter['name']} returns the fields {name} writes",
        })
    return out


def refine_with_llm(proposals: list[dict[str, Any]], *, docs: str | None = None, model: str = "claude-fable-5-1",
                    call: Any = None) -> list[dict[str, Any]]:
    """Ask a model which fields a read returns unchanged and which checks prove the write. Requires
    ANTHROPIC_API_KEY (or an injected `call(prompt) -> str` for tests). Proposals stay proposals."""
    prompt = ("You review read-back recipes for an AI-agent audit tool. For each proposal, return JSON with the same "
              "`name` and a `compare` object: `fields` (properties the read returns unchanged after the write) and "
              "optional `checks` ([{\"path\", \"equals\"}] that prove the write took effect, e.g. status). Only use "
              "fields you are confident exist. Output a JSON array only.\n\nProposals:\n" + json.dumps(proposals, indent=1)
              + ("\n\nAPI documentation excerpt:\n" + docs[:12000] if docs else ""))
    if call is None:  # pragma: no cover - network
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set (or pass call=)")
        import urllib.request
        body = json.dumps({"model": model, "max_tokens": 4000, "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST",
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            text = "".join(b.get("text", "") for b in json.loads(r.read()).get("content", []))
    else:
        text = call(prompt)
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return proposals
    try:
        refined = {x["name"]: x for x in json.loads(m.group(0)) if isinstance(x, dict) and x.get("name")}
    except json.JSONDecodeError:
        return proposals
    out = []
    for p in proposals:
        r = refined.get(p["name"])
        if r and isinstance(r.get("compare"), dict):
            p = {**p, "compare": {**p["compare"], **{k: v for k, v in r["compare"].items() if k in ("fields", "checks")}},
                 "source": p["source"] + "+llm"}
        out.append(p)
    return out
