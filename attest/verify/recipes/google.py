"""Google Calendar / Drive / Docs / Sheets — ported from DO `google.py` `verify()` (calendar, drive, docs, share)
and extended (sheets values, drive folders, docs title)."""
from __future__ import annotations

from typing import Any

from attest.descriptor import ActionDescriptor
from attest.verify.match import MatchReport, emails, equal, norm
from attest.verify.readers import GoogleCalendarReader, GoogleDocsReader, GoogleDriveReader, GoogleSheetsReader
from attest.verify.recipes import Recipe, register
from attest.verify.refs import first_id


# ── Calendar ──────────────────────────────────────────────────────────────────
def _cal_id(d: ActionDescriptor) -> str:
    return str(d.params.get("calendar_id") or d.params.get("calendarId") or "primary")


def fetch_event(reader: GoogleCalendarReader, d: ActionDescriptor, result: Any) -> Any:
    eid = d.params.get("event_id") or d.params.get("eventId") or first_id(result)
    return reader.event(str(eid), _cal_id(d)) if eid else None


def compare_event(d: ActionDescriptor, result: Any, ev: dict) -> MatchReport:
    r = MatchReport(matched=True)
    r.check("status:confirmed", ev.get("status") == "confirmed", status=ev.get("status"))
    summary = d.params.get("summary") or d.params.get("title")
    if summary and "summary" in ev:
        r.field_("summary", summary, ev.get("summary"))
    for key, want in (("start", d.params.get("start")), ("end", d.params.get("end"))):
        got = ev.get(key) or {}
        got_v = got.get("dateTime") or got.get("date") if isinstance(got, dict) else got
        want_v = (want.get("dateTime") or want.get("date")) if isinstance(want, dict) else want
        if want_v and got_v:
            r.field_(key, str(want_v)[:19], str(got_v)[:19])
    wanted = emails(d.params.get("attendees"))
    if wanted:
        got_att = [str(a.get("email", "")).lower() for a in ev.get("attendees") or [] if isinstance(a, dict)]
        for e in wanted:
            r.field_(f"attendee:{e}", e, ", ".join(got_att), e in got_att)
    return r


register(Recipe("calendar.event", "calendar", ("create", "update"), fetch_event, compare_event))


# ── Drive ─────────────────────────────────────────────────────────────────────
def fetch_file(reader: GoogleDriveReader, d: ActionDescriptor, result: Any) -> Any:
    fid = d.params.get("file_id") or d.params.get("fileId") or first_id(result)
    return reader.file(str(fid)) if fid else None


def compare_file(d: ActionDescriptor, result: Any, f: dict) -> MatchReport:
    r = MatchReport(matched=True)
    r.check("file:not-trashed", not f.get("trashed"))
    name = d.params.get("name") or d.params.get("title")
    if name and "name" in f:
        r.field_("name", name, f.get("name"))
    if d.params.get("mime_type") or d.params.get("mimeType"):
        r.field_("mimeType", d.params.get("mime_type") or d.params.get("mimeType"), f.get("mimeType"))
    parent = d.params.get("parent") or d.params.get("folder_id") or d.params.get("parents")
    if parent and f.get("parents"):
        wanted = parent if isinstance(parent, list) else [parent]
        r.field_("parents", wanted, f["parents"], all(p in f["parents"] for p in wanted))
    return r


def fetch_share(reader: GoogleDriveReader, d: ActionDescriptor, result: Any) -> Any:
    fid = d.params.get("file_id") or d.params.get("fileId") or d.target
    return {"permissions": reader.permissions(str(fid))} if fid else None


def compare_share(d: ActionDescriptor, result: Any, out: dict) -> MatchReport:
    r = MatchReport(matched=True)
    perms = out.get("permissions") or []
    for e in emails(d.params.get("email") or d.params.get("email_address") or d.params.get("emailAddress")
                    or d.params.get("share_with") or d.params.get("to")):
        hit = next((p for p in perms if str(p.get("emailAddress", "")).lower() == e), None)
        r.field_(f"shared:{e}", e, ", ".join(str(p.get("emailAddress", "")) for p in perms), hit is not None)
        role = d.params.get("role")
        if hit and role:
            r.field_("role", role, hit.get("role"))
    return r


def _is_share(d: ActionDescriptor, result: Any) -> bool:
    return d.verb == "share" or "permission" in (d.target or "").lower()


register(Recipe("drive.share", "drive", ("share", "create"), fetch_share, compare_share, when=_is_share))
register(Recipe("drive.file", "drive", ("create", "update", "upload"), fetch_file, compare_file))


# ── Docs ──────────────────────────────────────────────────────────────────────
def _doc_text(doc: dict) -> str:
    out = []
    for el in (doc.get("body") or {}).get("content") or []:
        for pe in (el.get("paragraph") or {}).get("elements") or []:
            out.append((pe.get("textRun") or {}).get("content") or "")
    return " ".join("".join(out).split())


def fetch_doc(reader: GoogleDocsReader, d: ActionDescriptor, result: Any) -> Any:
    did = d.params.get("document_id") or d.params.get("documentId") or first_id(result, "documentId")
    return reader.document(str(did)) if did else None


def compare_doc(d: ActionDescriptor, result: Any, doc: dict) -> MatchReport:
    r = MatchReport(matched=True)
    title = d.params.get("title") or d.params.get("name")
    if title and "title" in doc:
        r.field_("title", title, doc.get("title"))
    text = d.params.get("text") or d.params.get("body") or d.params.get("content")
    if text:
        probe = " ".join(str(text).split())[-120:]
        r.check("text:present", bool(probe) and probe in _doc_text(doc), probe=probe[:40])
    return r


register(Recipe("docs.document", "docs", ("create", "update", "write"), fetch_doc, compare_doc))


# ── Sheets ────────────────────────────────────────────────────────────────────
def fetch_sheet(reader: GoogleSheetsReader, d: ActionDescriptor, result: Any) -> Any:
    sid = d.params.get("spreadsheet_id") or d.params.get("spreadsheetId") or first_id(result, "spreadsheetId")
    if not sid:
        return None
    rng = d.params.get("range")
    if rng and (d.params.get("values") is not None):
        return {"values": reader.values(str(sid), str(rng)), "range": rng}
    return reader.spreadsheet(str(sid))


def compare_sheet(d: ActionDescriptor, result: Any, got: dict) -> MatchReport:
    r = MatchReport(matched=True)
    if "values" in got and d.params.get("values") is not None:
        want = [[norm(c) for c in row] for row in d.params["values"]]
        have = [[norm(c) for c in row] for row in got.get("values") or []]
        ok = all(any(row == h[:len(row)] for h in have) for row in want)
        r.field_("values", f"{len(want)} row(s)", f"{len(have)} row(s)", ok)
        return r
    title = d.params.get("title") or d.params.get("name")
    if title:
        r.field_("title", title, (got.get("properties") or {}).get("title"))
    else:
        r.check("spreadsheet:exists", bool(got.get("spreadsheetId")))
    return r


register(Recipe("sheets.spreadsheet", "sheets", ("create", "update", "write"), fetch_sheet, compare_sheet))
_ = equal
