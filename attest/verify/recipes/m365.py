"""Microsoft 365 via Graph — Outlook send (sentitems search by subject + recipients: Graph's sendMail returns
no id), Outlook events, Teams channel / chat messages."""
from __future__ import annotations

import html
import re
from typing import Any

from attest.descriptor import ActionDescriptor
from attest.verify.match import MatchReport, emails
from attest.verify.readers import GraphReader
from attest.verify.recipes import Recipe, register
from attest.verify.refs import dig, first_id

_TAGS = re.compile(r"<[^>]+>")


def _recipients(msg: dict) -> list[str]:
    out = []
    for k in ("toRecipients", "ccRecipients", "bccRecipients"):
        for r in msg.get(k) or []:
            addr = (r.get("emailAddress") or {}).get("address")
            if addr:
                out.append(addr.lower())
    return out


def _subject(d: ActionDescriptor) -> str | None:
    return d.params.get("subject") or dig(d.params, "message.subject")


def _wanted(d: ActionDescriptor) -> list[str]:
    out: list[str] = []
    for k in ("to", "cc", "bcc", "recipients"):
        out += emails(d.params.get(k))
    for k in ("toRecipients", "ccRecipients"):
        for r in dig(d.params, f"message.{k}") or []:
            out += emails((r.get("emailAddress") or {}).get("address") if isinstance(r, dict) else r)
    return out


def fetch_sent(reader: GraphReader, d: ActionDescriptor, result: Any) -> Any:
    subj = _subject(d)
    if not subj:
        return None
    msgs = reader.sent_messages(str(subj))
    wanted = set(_wanted(d))
    for m in msgs:
        if not wanted or wanted <= set(_recipients(m)):
            return m
    return {"_candidates": msgs} if msgs else None


def compare_sent(d: ActionDescriptor, result: Any, msg: dict) -> MatchReport:
    r = MatchReport(matched=True)
    if "_candidates" in msg:
        got = ", ".join(", ".join(_recipients(m)) for m in msg["_candidates"])
        for e in _wanted(d):
            r.field_(f"recipient:{e}", e, got, False)
        return r
    r.check("sentitems:found", bool(msg.get("id")))
    got = _recipients(msg)
    for e in _wanted(d):
        r.field_(f"recipient:{e}", e, ", ".join(got), e in got)
    subj = _subject(d)
    if subj:
        r.field_("subject", subj, msg.get("subject"))
    return r


def fetch_event(reader: GraphReader, d: ActionDescriptor, result: Any) -> Any:
    eid = d.params.get("event_id") or d.params.get("eventId") or first_id(result)
    return reader.event(str(eid)) if eid else None


def compare_event(d: ActionDescriptor, result: Any, ev: dict) -> MatchReport:
    r = MatchReport(matched=True)
    r.check("event:not-cancelled", not ev.get("isCancelled"))
    if d.params.get("subject") and "subject" in ev:
        r.field_("subject", d.params["subject"], ev.get("subject"))
    for key in ("start", "end"):
        want = d.params.get(key)
        want_v = want.get("dateTime") if isinstance(want, dict) else want
        got_v = (ev.get(key) or {}).get("dateTime") if isinstance(ev.get(key), dict) else ev.get(key)
        if want_v and got_v:
            r.field_(key, str(want_v)[:19], str(got_v)[:19])
    wanted = emails(d.params.get("attendees"))
    if wanted:
        got = [str((a.get("emailAddress") or {}).get("address", "")).lower() for a in ev.get("attendees") or []]
        for e in wanted:
            r.field_(f"attendee:{e}", e, ", ".join(got), e in got)
    return r


def fetch_teams_message(reader: GraphReader, d: ActionDescriptor, result: Any) -> Any:
    mid = first_id(result)
    if not mid:
        return None
    team, channel, chat = d.params.get("team_id") or d.params.get("teamId"), \
        d.params.get("channel_id") or d.params.get("channelId"), d.params.get("chat_id") or d.params.get("chatId")
    if chat:
        return reader.chat_message(str(chat), str(mid))
    if team and channel:
        return reader.channel_message(str(team), str(channel), str(mid))
    return None


def compare_teams_message(d: ActionDescriptor, result: Any, msg: dict) -> MatchReport:
    r = MatchReport(matched=True)
    want = d.params.get("text") or d.params.get("content") or dig(d.params, "body.content")
    if want is not None:
        got = html.unescape(_TAGS.sub("", str((msg.get("body") or {}).get("content", ""))))
        r.field_("text", " ".join(str(want).split()), " ".join(got.split()))
    else:
        r.check("message:exists", bool(msg.get("id")))
    return r


def _is_event(d: ActionDescriptor, result: Any) -> bool:
    return "event" in (d.target or "").lower() or "start" in d.params


register(Recipe("outlook.event", "outlook", ("create", "update"), fetch_event, compare_event, when=_is_event))
register(Recipe("outlook.send", "outlook", ("send", "reply"), fetch_sent, compare_sent))
register(Recipe("teams.message", "teams", ("send", "create", "reply"), fetch_teams_message, compare_teams_message))
