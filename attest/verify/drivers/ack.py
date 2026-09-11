"""L1 — did the result look like an acknowledgement? An id, a success flag, a 2xx status.
This is what "the API returned 200" is worth: recorded as `acknowledged`, never as `verified`."""
from __future__ import annotations

from typing import Any

ID_KEYS = ("id", "ts", "message_id", "messageId", "thread_id", "threadId", "resource_name", "resourceName", "key",
           "uuid", "uid", "sid", "object_id", "objectId", "documentId", "spreadsheetId", "permission_id", "url",
           "permalink", "html_url", "number")
OK_KEYS = ("ok", "success", "sent", "created", "updated", "deleted", "accepted")
STATUS_OK = {"ok", "success", "succeeded", "sent", "created", "updated", "done", "completed", "accepted", "queued",
             "delivered", "active", "confirmed"}


def acknowledged(result: Any) -> tuple[bool, dict[str, Any]]:
    """→ (acknowledged?, evidence). Evidence holds only ids and status, never content."""
    if result is None:
        return False, {"detail": "no result"}
    ev: dict[str, Any] = {}
    if isinstance(result, dict):
        if result.get("error") and len(result) <= 2:
            return False, {"error": str(result.get("error"))[:200]}
        for k in OK_KEYS:
            if k in result and result[k] is False:
                return False, {k: False}
        for k in ID_KEYS:
            if result.get(k) not in (None, "", 0):
                ev[k] = str(result[k])[:120]
        for k in ("status", "state", "result"):
            v = result.get(k)
            if isinstance(v, str) and v.lower() in STATUS_OK:
                ev[k] = v
            elif isinstance(v, int) and 200 <= v < 300:
                ev[k] = v
        for k in OK_KEYS:
            if result.get(k) is True:
                ev[k] = True
        for k, v in result.items():
            if (k.endswith("_id") or k.endswith("Id")) and v not in (None, "", 0) and k not in ev:
                ev[k] = str(v)[:120]
        return bool(ev), ev or {"detail": "response carried no id or success status"}
    status_code = getattr(result, "status_code", None) or getattr(result, "status", None)
    if isinstance(status_code, int):
        ev["status_code"] = status_code
        return 200 <= status_code < 300, ev
    for k in ID_KEYS:
        v = getattr(result, k, None)
        if v not in (None, "") and not callable(v):
            ev[k] = str(v)[:120]
    if ev:
        return True, ev
    if isinstance(result, bool):
        return result, {"bool": result}
    if isinstance(result, (str, int)) and result not in ("", 0):
        return True, {"value": str(result)[:120]}
    if isinstance(result, (list, tuple)):
        return len(result) > 0, {"count": len(result)}
    return False, {"detail": f"unrecognised result type {type(result).__name__}"}
