"""System / verb detection from SDK call paths and plain function names.

    hubspot.crm.deals.update       → hubspot, update, target=crm.deals
    gmail.users().messages().send  → gmail, send, target=messages
    send_email                     → unknown, send, target=email
"""
from __future__ import annotations

import re

from attest.registry.mcp_names import nouns, split_system
from attest.registry.verbs import classify

_CALL = re.compile(r"\(\)")
_SPLIT = re.compile(r"[._\-\s]+|(?<=[a-z0-9])(?=[A-Z])")


def detect(path: str) -> tuple[str, str, str | None, bool]:
    clean = _CALL.sub("", path or "")
    toks = [t.lower() for t in _SPLIT.split(clean) if t]
    system, rest = split_system(toks)
    verb, recognised = classify(rest)
    rest = [t for t in rest if t not in {"users", "me", "api", "v1", "v2", "v3"}]
    target = nouns(rest)
    return system, verb, (target.replace("_", ".") if target else None), recognised
