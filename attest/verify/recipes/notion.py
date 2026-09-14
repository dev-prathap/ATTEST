"""Notion — create / update page ⇒ pages.retrieve; create database ⇒ databases.retrieve. Field compare on
title and simple property types (title, rich_text, select, status, checkbox, number, url, email)."""
from __future__ import annotations

from typing import Any

from attest.descriptor import ActionDescriptor
from attest.verify.match import MatchReport, equal
from attest.verify.readers import NotionReader
from attest.verify.recipes import Recipe, register
from attest.verify.refs import first_id


def _plain(prop: Any) -> Any:
    """Flatten a Notion property value to something comparable."""
    if not isinstance(prop, dict):
        return prop
    t = prop.get("type")
    v = prop.get(t) if t else None
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text") or (x.get("text") or {}).get("content", "") for x in v or [])
    if t in ("select", "status"):
        return (v or {}).get("name")
    if t == "multi_select":
        return [x.get("name") for x in v or []]
    if t in ("checkbox", "number", "url", "email", "phone_number"):
        return v
    if t == "date":
        return (v or {}).get("start")
    return v


def _wanted(d: ActionDescriptor) -> dict[str, Any]:
    props = d.params.get("properties")
    if isinstance(props, dict):
        return {k: _plain(v) if isinstance(v, dict) and "type" in v else _flatten_input(v) for k, v in props.items()}
    return {}


def _flatten_input(v: Any) -> Any:
    """Input shapes without `type`: {"title": [{"text": {"content": "X"}}]} / {"select": {"name": "Y"}}."""
    if isinstance(v, dict) and len(v) == 1:
        (t, inner), = v.items()
        return _plain({"type": t, t: inner})
    return v


def fetch_page(reader: NotionReader, d: ActionDescriptor, result: Any) -> Any:
    pid = d.params.get("page_id") or d.params.get("pageId") or first_id(result)
    return reader.page(str(pid)) if pid else None


def compare_page(d: ActionDescriptor, result: Any, page: dict) -> MatchReport:
    r = MatchReport(matched=True)
    r.check("page:not-archived", not page.get("archived"))
    got = {k: _plain(v) for k, v in (page.get("properties") or {}).items()}
    for k, want in _wanted(d).items():
        if k in got and want is not None:
            r.field_(k, want, got[k], equal(want, got[k]))
    title = d.params.get("title")
    if title and not _wanted(d):
        props = page.get("properties") or {}
        got_title = next((v for k, v in got.items() if props.get(k, {}).get("type") == "title"), None)
        if got_title is not None:
            r.field_("title", title, got_title)
    parent = d.params.get("parent")
    if isinstance(parent, dict) and page.get("parent"):
        for k in ("database_id", "page_id"):
            if parent.get(k):
                r.field_(f"parent.{k}", parent[k].replace("-", ""), str(page["parent"].get(k, "")).replace("-", ""))
    return r


def fetch_database(reader: NotionReader, d: ActionDescriptor, result: Any) -> Any:
    did = d.params.get("database_id") or first_id(result)
    return reader.database(str(did)) if did else None


def compare_database(d: ActionDescriptor, result: Any, db: dict) -> MatchReport:
    r = MatchReport(matched=True)
    r.check("database:exists", bool(db.get("id")))
    title = d.params.get("title")
    if isinstance(title, list):
        title = "".join((x.get("text") or {}).get("content", "") for x in title)
    if title:
        r.field_("title", title, _plain({"type": "title", "title": db.get("title") or []}))
    return r


def _is_db(d: ActionDescriptor, result: Any) -> bool:
    return "database" in (d.target or "").lower() and "page" not in (d.target or "").lower() \
        and not d.params.get("page_id")


register(Recipe("notion.database", "notion", ("create",), fetch_database, compare_database, when=_is_db))
register(Recipe("notion.page", "notion", ("create", "update", "write"), fetch_page, compare_page))
