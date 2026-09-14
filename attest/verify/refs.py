"""Reference expressions used by declarative read-back pairs — lifted from DO `execution/actions.py`.

    "$.id"                 → result["id"]
    "$.data.deal_id"       → result["data"]["deal_id"]
    "$params.calendarId"   → params["calendarId"]
    "$params.calendarId|primary"   → params["calendarId"], or "primary" when missing/empty
    "$.items[0].id"        → result["items"][0]["id"]
Anything not starting with `$` is a literal.
"""
from __future__ import annotations

import re
from typing import Any

_PART = re.compile(r"[^.\[\]]+|\[\d+\]")


def dig(obj: Any, path: str) -> Any:
    cur = obj
    for part in _PART.findall(path or ""):
        if part.startswith("["):
            idx = int(part[1:-1])
            cur = cur[idx] if isinstance(cur, (list, tuple)) and len(cur) > idx else None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None) if cur is not None and not isinstance(cur, (str, int, float)) else None
        if cur is None:
            return None
    return cur


def resolve(expr: Any, params: dict[str, Any], result: Any) -> Any:
    if not isinstance(expr, str) or not expr.startswith("$"):
        return expr
    src, _, rest = expr.partition(".")
    path, _, default = rest.partition("|")
    val = dig(params if src == "$params" else result, path)
    return val if val not in (None, "") else (default or None)


def resolve_all(spec: dict[str, Any], params: dict[str, Any], result: Any) -> dict[str, Any]:
    return {k: resolve(v, params, result) for k, v in (spec or {}).items()}


def first_id(result: Any, *extra_keys: str) -> str | None:
    """Best-effort id from a write's response: `id`, `Id`, `ID`, `_id`, `<anything>_id`, `key`, `uuid`."""
    if result is None:
        return None
    if isinstance(result, (str, int)) and str(result):
        return str(result)
    keys = (*extra_keys, "id", "Id", "ID", "_id", "uuid", "key", "record_id", "recordId", "object_id", "objectId")
    if isinstance(result, dict):
        for k in keys:
            if result.get(k) not in (None, ""):
                return str(result[k])
        for k, v in result.items():
            if (k.endswith("_id") or k.endswith("Id")) and v not in (None, ""):
                return str(v)
        for k in ("data", "result", "object", "record"):
            if isinstance(result.get(k), dict):
                inner = first_id(result[k])
                if inner:
                    return inner
        return None
    for k in keys:
        v = getattr(result, k, None)
        if v not in (None, "") and not callable(v):
            return str(v)
    return None
