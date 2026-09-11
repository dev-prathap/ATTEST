"""System / verb detection from an outbound HTTP call (method + URL).

    POST https://gmail.googleapis.com/gmail/v1/users/me/messages/send     → gmail, send
    PATCH https://api.hubapi.com/crm/v3/objects/deals/123                  → hubspot, update, target=deals/123
    POST https://api.someweirdcrm.io/v2/leads                              → someweirdcrm, create, target=leads
    POST https://api.stripe.com/v1/charges                                 → stripe, pay

The HTTP method is the baseline; a side-effect word in the last path segments (`/send`, `/permissions`,
`chat.postMessage`, `/charges`) refines it. DELETE is never overridden.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from attest.registry.mcp_names import tokens
from attest.registry.systems import system_for_host
from attest.registry.verbs import GET_WORDS, LIST_WORDS, MONEY_NOUNS, SEARCH_WORDS, VERB_MAP, classify, singular

_ID_SEG = re.compile(
    r"^(\d+|me|primary|\{[^}]+\}|[0-9a-f-]{8,}|[A-Za-z]{1,5}[-_]\d+|(?=.*\d)[A-Za-z0-9_.\-]{5,}|[A-Za-z0-9_-]{20,})$"
)
_VERSION = re.compile(r"^v\d+(\.\d+)?$")
_NOISE = {"users", "me", "api", "rest", "graphql", "v1", "v2", "v3"}
_STRONG = {"share", "pay", "approve", "execute", "send", "reply", "upload"}


def _segments(path: str) -> list[str]:
    return [s for s in path.split("/") if s and not _VERSION.match(s)]


def _looks_like_id(seg: str) -> bool:
    return bool(_ID_SEG.match(seg)) and not _VERSION.match(seg)


def _word_verb(w: str) -> str | None:
    """Verb for one path word, tolerant of plural collection names (`charges` → pay, `messages` → send)."""
    for cand in (w, singular(w)):
        if cand in SEARCH_WORDS:
            return "search"
        if cand in VERB_MAP:
            return VERB_MAP[cand]
    return None


def detect(method: str, url: str) -> tuple[str, str, str | None, bool]:
    """→ (system, verb, target, recognised)."""
    method = (method or "GET").upper()
    parts = urlsplit(url if "://" in url else "https://" + url)
    host, path, query = parts.netloc.lower(), parts.path, parts.query
    system = system_for_host(host, path)
    segs = _segments(path)
    non_id = [s for s in segs if not _looks_like_id(s)]
    words = [w for s in non_id for w in tokens(s)]

    path_verb, path_word = None, None
    for w in reversed(words[-3:]):
        v = _word_verb(w)
        if v and v not in ("create", "update"):
            path_verb, path_word = v, w
            break

    recognised = True
    if method in ("GET", "HEAD", "OPTIONS"):
        if path_verb == "search" or "q=" in query or "query=" in query or "search" in words:
            verb = "search"
        elif segs and _looks_like_id(segs[-1]):
            verb = "get"
        elif words and words[-1] in GET_WORDS | LIST_WORDS:
            verb = classify([words[-1]])[0]
        else:
            verb = "list"
    elif method == "DELETE":
        verb = "delete"
    elif method == "POST":
        if path_verb and path_verb not in ("get", "list", "search"):
            verb = path_verb
        elif segs and _looks_like_id(segs[-1]):
            verb = "update"
        else:
            verb = "create"
    elif method in ("PUT", "PATCH"):
        verb = path_verb if path_verb in _STRONG else "update"
    else:
        verb, recognised = "write", False
    if verb in ("create", "update", "write") and any(w in MONEY_NOUNS or singular(w) in MONEY_NOUNS for w in words):
        verb = "pay"

    resource = [s for s in segs if s.lower() not in _NOISE]
    if path_word and resource and path_word in tokens(resource[-1]) and not _looks_like_id(resource[-1]):
        resource = resource[:-1]
    target = "/".join(resource[-2:]) if resource else None
    return system, verb, target, recognised
