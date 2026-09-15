"""Declarative recipes (P3.4): JSON files a human can review and the community can contribute.

    {
      "name": "someweirdcrm.lead", "system": "someweirdcrm", "verbs": ["create", "update"], "target": "lead",
      "read": {"method": "GET", "url": "https://api.someweirdcrm.io/v2/leads/{id}", "id": "$.id|$params.lead_id"},
      "compare": {"fields": ["name", "email", "stage"], "exists": true},
      "source": "openapi|mcp|llm|community", "version": 1
    }

`read.url` is templated with `{id}` (resolved through the `$.` / `$params.` refs) and any `{param}` from the
write's params. `compare.fields` are compared on the fetched record (top level or under properties/data);
`compare.checks` are `{ "path": "status", "equals": "confirmed" }` assertions. Loaded from `registry/recipes/`
in the repo, `$ATTEST_RECIPES_DIR`, and `~/.attest/recipes`.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from attest.descriptor import ActionDescriptor
from attest.verify.match import MatchReport, compare_overlap, equal
from attest.verify.readers import BaseReader, HttpReader, ReadBackError
from attest.verify.recipes import Recipe, register
from attest.verify.refs import dig, resolve

_TPL = re.compile(r"\{([^}]+)\}")


def _first_ref(exprs: str, params: dict[str, Any], result: Any) -> Any:
    for expr in exprs.split("|") if "|" in exprs and exprs.startswith("$") and "$" in exprs[1:] else [exprs]:
        v = resolve(expr, params, result)
        if v not in (None, ""):
            return v
    return resolve(exprs, params, result)


def _fill(url: str, d: ActionDescriptor, result: Any, id_expr: str | None) -> str | None:
    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key == "id":
            v = _first_ref(id_expr or "$.id", d.params, result)
        else:
            v = d.params.get(key) or dig(result, key)
        if v in (None, ""):
            raise KeyError(key)
        return str(v)
    try:
        return _TPL.sub(repl, url)
    except KeyError:
        return None


def make_recipe(spec: dict[str, Any]) -> Recipe:
    read, cmp = spec.get("read") or {}, spec.get("compare") or {}
    target_word = (spec.get("target") or "").lower()

    def when(d: ActionDescriptor, result: Any) -> bool:
        return not target_word or target_word in (d.target or "").lower() or any(target_word in k.lower() for k in d.params)

    def fetch(reader: BaseReader, d: ActionDescriptor, result: Any) -> Any:
        url = _fill(str(read.get("url", "")), d, result, read.get("id"))
        if not url:
            return None
        params = {k: _fill(str(v), d, result, read.get("id")) for k, v in (read.get("params") or {}).items()}
        try:
            if isinstance(reader, HttpReader):
                return reader.get(url, params)
            return reader.fetch(url, params)
        except ReadBackError as e:
            if "404" in str(e):
                return None
            raise

    def compare(d: ActionDescriptor, result: Any, fetched: Any) -> MatchReport:
        r = MatchReport(matched=True)
        if not isinstance(fetched, dict):
            r.check("record:exists", fetched is not None)
            return r
        fields = cmp.get("fields")
        want = {k: v for k, v in d.params.items() if fields is None or k in fields}
        if isinstance(d.params.get("properties"), dict):
            want.update({k: v for k, v in d.params["properties"].items() if fields is None or k in fields})
        compare_overlap(r, want, fetched)
        for chk in cmp.get("checks") or []:
            got = dig(fetched, chk["path"])
            if "equals" in chk:
                r.field_(chk["path"], chk["equals"], got, equal(chk["equals"], got))
            elif "contains" in chk:
                r.check(f"{chk['path']}:contains:{chk['contains']}", chk["contains"] in (got or []))
        if r.compared == 0 and cmp.get("exists", True):
            r.check("record:exists", True)
        return r

    return Recipe(spec["name"], spec["system"], tuple(spec.get("verbs") or ("create", "update")), fetch, compare,
                  when=when, source=spec.get("source", "community"))


def load_dir(path: str | Path) -> list[Recipe]:
    out: list[Recipe] = []
    p = Path(path)
    if not p.is_dir():
        return out
    for f in sorted(p.glob("*.json")):
        try:
            spec = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        for item in spec if isinstance(spec, list) else [spec]:
            if item.get("name") and item.get("system") and item.get("read"):
                out.append(register(make_recipe(item)))
    return out


def load_all() -> list[Recipe]:
    dirs = [Path(__file__).resolve().parents[3] / "registry" / "recipes", Path(os.environ.get("ATTEST_RECIPES_DIR", "")),
            Path.home() / ".attest" / "recipes"]
    out: list[Recipe] = []
    for d in dirs:
        if str(d) and d.is_dir():
            out += load_dir(d)
    return out
