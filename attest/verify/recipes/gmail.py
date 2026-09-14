"""Gmail — ported from DO `connectors/providers/google.py` `GoogleConnector.verify()`.

send / reply   messages.get(id, metadata To/Cc/Subject) ⇒ SENT label, intended recipients ⊂ To/Cc, subject,
               reply keeps threadId
create draft   drafts.get(id) ⇒ exists
update labels  messages.get(id, minimal) ⇒ added ⊂ labels and removed ∩ labels = ∅
"""
from __future__ import annotations

from typing import Any

from attest.descriptor import ActionDescriptor
from attest.verify.match import MatchReport, emails, equal
from attest.verify.readers import GmailReader
from attest.verify.recipes import Recipe, register
from attest.verify.refs import first_id

_LABEL_KEYS_ADD = ("add_labels", "addLabelIds", "add_label_ids", "labels_add")
_LABEL_KEYS_REMOVE = ("remove_labels", "removeLabelIds", "remove_label_ids", "labels_remove")


def _headers(msg: dict) -> dict[str, str]:
    out = {}
    for h in ((msg.get("payload") or {}).get("headers") or []):
        out[str(h.get("name", "")).lower()] = str(h.get("value", ""))
    return out


def _wanted_recipients(d: ActionDescriptor) -> list[str]:
    out: list[str] = []
    for k in ("to", "cc", "bcc", "recipients", "recipient"):
        out += emails(d.params.get(k))
    if not out and d.target:
        out += emails(d.target)
    return out


def _is_reply(d: ActionDescriptor, result: Any) -> bool:
    if d.verb == "reply":
        return True
    return any(k in d.params for k in ("thread_id", "threadId", "in_reply_to", "message_id")) and d.verb == "send"


def fetch_message(reader: GmailReader, d: ActionDescriptor, result: Any) -> Any:
    mid = first_id(result, "message_id", "messageId")
    return reader.message(mid) if mid else None


def compare_send(d: ActionDescriptor, result: Any, msg: dict) -> MatchReport:
    r = MatchReport(matched=True)
    labels = set(msg.get("labelIds") or [])
    r.check("label:SENT", "SENT" in labels, labels=sorted(labels))
    h = _headers(msg)
    got = emails(h.get("to", "")) + emails(h.get("cc", "")) + emails(h.get("bcc", ""))
    for e in _wanted_recipients(d):
        r.field_(f"recipient:{e}", e, ", ".join(got), e in got)
    subj = d.params.get("subject")
    if subj and "subject" in h:
        r.field_("subject", subj, h["subject"], equal(subj, h["subject"]))
    if _is_reply(d, result):
        want_thread = ((isinstance(result, dict) and result.get("threadId")) or d.params.get("thread_id")
                       or d.params.get("threadId"))
        if want_thread:
            r.field_("threadId", want_thread, msg.get("threadId"))
    return r


def fetch_draft(reader: GmailReader, d: ActionDescriptor, result: Any) -> Any:
    did = first_id(result, "draft_id", "draftId")
    return reader.draft(did) if did else None


def compare_draft(d: ActionDescriptor, result: Any, draft: dict) -> MatchReport:
    r = MatchReport(matched=True)
    r.check("draft:exists", bool(draft.get("id")))
    msg = draft.get("message") or {}
    if msg:
        h = _headers(msg)
        for e in _wanted_recipients(d):
            got = emails(h.get("to", "")) + emails(h.get("cc", ""))
            if got:
                r.field_(f"recipient:{e}", e, ", ".join(got), e in got)
        if d.params.get("subject") and "subject" in h:
            r.field_("subject", d.params["subject"], h["subject"])
    return r


def fetch_labels(reader: GmailReader, d: ActionDescriptor, result: Any) -> Any:
    mid = d.params.get("message_id") or d.params.get("messageId") or d.params.get("id") or first_id(result)
    return reader.message_labels(mid) if mid else None


def compare_labels(d: ActionDescriptor, result: Any, msg: dict) -> MatchReport:
    r = MatchReport(matched=True)
    labels = set(msg.get("labelIds") or [])
    add = next((d.params[k] for k in _LABEL_KEYS_ADD if d.params.get(k)), []) or []
    rem = next((d.params[k] for k in _LABEL_KEYS_REMOVE if d.params.get(k)), []) or []
    for lab in add:
        r.check(f"label:+{lab}", lab in labels)
    for lab in rem:
        r.check(f"label:-{lab}", lab not in labels)
    r.notes.append(f"labels={sorted(labels)}")
    return r


def _is_label_update(d: ActionDescriptor, result: Any) -> bool:
    return any(k in d.params for k in _LABEL_KEYS_ADD + _LABEL_KEYS_REMOVE)


def _is_draft(d: ActionDescriptor, result: Any) -> bool:
    t = (d.target or "").lower()
    return "draft" in t or (isinstance(result, dict) and "message" in result and "id" in result)


register(Recipe("gmail.send", "gmail", ("send", "reply"), fetch_message, compare_send))
register(Recipe("gmail.draft", "gmail", ("create", "write"), fetch_draft, compare_draft, when=_is_draft))
register(Recipe("gmail.labels", "gmail", ("update", "write"), fetch_labels, compare_labels, when=_is_label_update))
