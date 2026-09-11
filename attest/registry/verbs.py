"""Verb taxonomy, aliasing and risk-by-verb. Lifted from DO `template.py` (VERB_MAP, _verb, _risk)
and `capabilities.py`; extended with pay / approve / execute / write (doc 03 §1).

One change from DO: an unrecognised side-effect word classifies as `write` (not `update`),
so the ledger never claims a verb it did not detect.
"""
from __future__ import annotations

from attest.descriptor import READ_VERBS, WRITE_VERBS

GET_WORDS = {"get", "fetch", "lookup", "find", "whoami", "count", "download", "read", "check", "describe",
             "retrieve", "export", "view", "show", "load", "head"}
SEARCH_WORDS = {"search", "query", "filter"}
LIST_WORDS = {"list", "ls", "index"}

VERB_MAP: dict[str, str] = {
    "send": "send", "post": "send", "forward": "send", "email": "send", "message": "send", "notify": "send",
    "reply": "reply", "respond": "reply",
    "create": "create", "add": "create", "invite": "create", "schedule": "create", "open": "create",
    "append": "create", "duplicate": "create", "comment": "create", "import": "create", "new": "create",
    "clone": "create", "copy": "create", "start": "create", "insert": "create", "book": "create", "put": "create",
    "upload": "upload", "attach": "upload",
    "archive": "update", "unarchive": "update", "update": "update", "set": "update", "rename": "update",
    "pin": "update", "unpin": "update", "mark": "update", "join": "update", "leave": "update", "move": "update",
    "assign": "update", "unassign": "update", "close": "update", "reopen": "update", "restore": "update",
    "star": "update", "unstar": "update", "modify": "update", "edit": "update", "untrash": "update",
    "change": "update", "convert": "update", "merge": "update", "publish": "update", "unpublish": "update",
    "resolve": "update", "complete": "update", "react": "update", "stop": "update", "enable": "update",
    "disable": "update", "reject": "update", "label": "update", "unlabel": "update", "patch": "update",
    "watch": "update", "unwatch": "update", "subscribe": "update", "unsubscribe": "update", "snooze": "update",
    "upsert": "update", "replace": "update", "toggle": "update",
    "share": "share", "grant": "share", "permission": "share", "permissions": "share", "acl": "share",
    "delete": "delete", "remove": "delete", "cancel": "delete", "trash": "delete", "revoke": "delete",
    "purge": "delete", "clear": "delete", "destroy": "delete", "drop": "delete",
    "pay": "pay", "charge": "pay", "transfer": "pay", "refund": "pay", "payout": "pay", "payment": "pay",
    "payments": "pay", "withdraw": "pay", "deposit": "pay", "settle": "pay",
    "approve": "approve", "authorize": "approve", "authorise": "approve", "sign": "approve",
    "execute": "execute", "run": "execute", "trigger": "execute", "invoke": "execute", "deploy": "execute",
    "exec": "execute", "call": "execute", "dispatch": "execute",
}

RISK_BY_VERB: dict[str, str] = {
    "read": "low", "search": "low", "get": "low", "list": "low",
    "update": "medium", "write": "medium", "upload": "medium",
    "send": "high", "reply": "high", "create": "high", "share": "high", "approve": "high", "execute": "high",
    "delete": "very_high", "pay": "very_high",
}

# Human-reviewed overrides keyed by normalized action id (system_words). Seed from DO; grows with the registry.
VERB_OVERRIDES: dict[str, str] = {
    "onedrive_invite_recipients": "share", "onedrive_create_sharing_link": "share",
    "onedrive_delete_permission": "update",
    "sharepoint_create_sharing_link": "share", "sharepoint_add_drive_item_permission": "share",
    "sharepoint_update_drive_item_permission": "share", "sharepoint_remove_drive_item_permission": "update",
    "sharepoint_publish_site_page": "update", "sharepoint_restore_drive_item_version": "update",
    "teams_add_team_member": "update", "teams_remove_team_member": "update", "outlook_cancel_event": "update",
    "zoho_crm_convert_lead": "update", "zoho_crm_upsert_records": "update",
    "calendar_create_acl_rule": "share", "calendar_update_acl_rule": "share",
    "drive_update_permission": "share", "drive_list_permissions": "list", "drive_get_permission": "get",
    "drive_create_permission": "share", "drive_share_file": "share",
    "slack_remove_reaction": "update", "slack_add_reaction": "update",
    "gmail_send_message": "send", "gmail_reply_message": "reply", "gmail_create_draft": "create",
}
RISK_OVERRIDES: dict[str, str] = {
    "outlook_cancel_event": "high", "teams_remove_team_member": "high", "sharepoint_publish_site_page": "high",
    "zoho_crm_convert_lead": "high", "zoho_crm_upsert_records": "high",
    "onedrive_delete_permission": "medium", "sharepoint_remove_drive_item_permission": "medium",
    "slack_add_reaction": "low", "slack_remove_reaction": "low", "slack_mark_as_read": "low",
    "slack_set_status": "medium", "slack_set_user_presence": "medium", "slack_open_dm": "medium",
    "slack_join_channel": "medium", "slack_leave_channel": "medium",
    "gmail_create_draft": "medium", "gmail_update_labels": "medium",
}

# Creating or changing one of these objects moves money: create/update ⇒ pay (very high risk).
MONEY_NOUNS = {"charge", "refund", "transfer", "payout", "payment", "withdrawal", "disbursement", "wire"}

_STRIP_PREFIX = {"batch", "bulk", "async", "do", "try", "safe"}


def singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def classify(tokens: list[str], *, default_write: str = "write") -> tuple[str, bool]:
    """(verb, recognised). Scans tokens left-to-right for the first verb-bearing word.
    Unrecognised ⇒ (`default_write`, False) so callers can raise the risk tier."""
    toks = [t.lower() for t in tokens if t]
    while toks and toks[0] in _STRIP_PREFIX and len(toks) > 1:
        toks = toks[1:]
    verb, recognised = default_write, False
    for t in toks:
        if t in SEARCH_WORDS:
            verb, recognised = "search", True
            break
        if t in LIST_WORDS:
            verb, recognised = "list", True
            break
        if t in GET_WORDS:
            verb, recognised = "get", True
            break
        if t in VERB_MAP:
            verb, recognised = VERB_MAP[t], True
            break
    if verb in ("create", "update", "write") and any(singular(t) in MONEY_NOUNS for t in toks):
        return "pay", True
    return verb, recognised


def risk_for(verb: str, *, recognised: bool = True, action_id: str | None = None) -> str:
    """Risk tier for a verb. Unrecognised side effects are `high` — an unknown write must confirm."""
    if action_id and action_id in RISK_OVERRIDES:
        return RISK_OVERRIDES[action_id]
    if verb == "delete":
        return "very_high"
    if not recognised and verb not in READ_VERBS:
        return "high"
    return RISK_BY_VERB.get(verb, "medium")


def is_write(verb: str) -> bool:
    return verb in WRITE_VERBS
