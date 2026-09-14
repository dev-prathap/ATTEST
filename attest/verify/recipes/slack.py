"""Slack — new field-comparing recipes (DO had existence-only pairs through the Nango proxy).

send (chat.postMessage)   conversations.history(channel, latest=ts, inclusive, limit=1) ⇒ ts present,
                          text equal, channel equal
create channel            conversations.info(id) ⇒ exists, name equal
"""
from __future__ import annotations

from typing import Any

from attest.descriptor import ActionDescriptor
from attest.verify.match import MatchReport
from attest.verify.readers import SlackReader
from attest.verify.recipes import Recipe, register


def _channel(d: ActionDescriptor, result: Any) -> str | None:
    if isinstance(result, dict) and result.get("channel"):
        return str(result["channel"])
    return d.params.get("channel") or d.params.get("channel_id")


def fetch_message(reader: SlackReader, d: ActionDescriptor, result: Any) -> Any:
    ts = (result.get("ts") or (result.get("message") or {}).get("ts")) if isinstance(result, dict) else None
    ch = _channel(d, result)
    return reader.message(ch, str(ts)) if ts and ch else None


def compare_message(d: ActionDescriptor, result: Any, msg: dict) -> MatchReport:
    r = MatchReport(matched=True)
    want_ts = result.get("ts") if isinstance(result, dict) else None
    r.field_("ts", want_ts, msg.get("ts"), str(want_ts) == str(msg.get("ts")))
    text = d.params.get("text")
    if text is not None and "text" in msg:
        r.field_("text", text, msg.get("text"))
    thread = d.params.get("thread_ts")
    if thread:
        r.field_("thread_ts", thread, msg.get("thread_ts"), str(thread) == str(msg.get("thread_ts")))
    return r


def fetch_channel(reader: SlackReader, d: ActionDescriptor, result: Any) -> Any:
    cid = None
    if isinstance(result, dict):
        cid = (result.get("channel") or {}).get("id") if isinstance(result.get("channel"), dict) else result.get("id")
    return reader.channel(str(cid)) if cid else None


def compare_channel(d: ActionDescriptor, result: Any, ch: dict) -> MatchReport:
    r = MatchReport(matched=True)
    r.check("channel:exists", bool(ch.get("id")))
    if d.params.get("name") and ch.get("name"):
        r.field_("name", str(d.params["name"]).lstrip("#").lower(), ch.get("name"))
    if "is_private" in d.params and "is_private" in ch:
        r.field_("is_private", bool(d.params["is_private"]), bool(ch["is_private"]))
    return r


def _is_channel_create(d: ActionDescriptor, result: Any) -> bool:
    t = (d.target or "").lower()
    return ("channel" in t or "conversation" in t
            or (isinstance(result, dict) and isinstance(result.get("channel"), dict)))


register(Recipe("slack.send", "slack", ("send", "reply"), fetch_message, compare_message))
register(Recipe("slack.channel", "slack", ("create",), fetch_channel, compare_channel, when=_is_channel_create))
