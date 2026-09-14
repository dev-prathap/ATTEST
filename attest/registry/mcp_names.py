"""System / verb detection from MCP tool names.

    gmail_send_message            → gmail, send, target=message
    mcp__hubspot__update_deal     → hubspot, update, target=deal
    slack-post-message            → slack, send
    notion.pages.create           → notion, create, target=pages
"""
from __future__ import annotations

import re

from attest.registry.systems import SYSTEM_ALIASES, SYSTEM_LABELS, canonical_system
from attest.registry.verbs import VERB_OVERRIDES, classify

_SPLIT = re.compile(r"[_\-.:/\s]+|(?<=[a-z0-9])(?=[A-Z])")  # snake, kebab, dotted, camelCase


def tokens(name: str) -> list[str]:
    name = name.strip()
    if name.startswith("mcp__"):
        name = name[len("mcp__"):]
    return [t.lower() for t in _SPLIT.split(name) if t]


def split_system(toks: list[str], server: str | None = None) -> tuple[str, list[str]]:
    """Peel the system off the front of the token list. Tries two-token aliases first (google_calendar)."""
    if server:
        sys_ = canonical_system(server) or server.lower().replace("-", "_").replace(" ", "_")
        if toks and toks[0] in (sys_, *[k for k, v in SYSTEM_ALIASES.items() if v == sys_]):
            toks = toks[1:]
        return sys_, toks
    for n in (2, 1):
        if len(toks) >= n:
            head = "_".join(toks[:n])
            if head in SYSTEM_LABELS and head != "unknown":
                return head, toks[n:]
            if head in SYSTEM_ALIASES:
                return SYSTEM_ALIASES[head], toks[n:]
    return "unknown", toks


def detect(name: str, *, server: str | None = None) -> tuple[str, str, str | None, bool]:
    """→ (system, verb, target, recognised)."""
    toks = tokens(name)
    system, rest = split_system(toks, server)
    action_id = f"{system}_{'_'.join(rest)}" if rest else system
    if action_id in VERB_OVERRIDES:
        verb, recognised = VERB_OVERRIDES[action_id], True
    else:
        verb, recognised = classify(rest)
    return system, verb, nouns(rest), recognised


def nouns(rest: list[str]) -> str | None:
    """Everything after the first verb-bearing token is the target (`send_message` → message)."""
    from attest.registry.verbs import _STRIP_PREFIX, GET_WORDS, LIST_WORDS, SEARCH_WORDS, VERB_MAP
    verbish = set(VERB_MAP) | GET_WORDS | LIST_WORDS | SEARCH_WORDS
    toks = [t for t in rest if t not in _STRIP_PREFIX]
    idx = next((i for i, t in enumerate(toks) if t in verbish), None)
    if idx is None:
        return "_".join(toks) or None
    remaining = toks[:idx] + toks[idx + 1:]
    return "_".join(remaining) or None
