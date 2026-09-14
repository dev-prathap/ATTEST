"""Convention driver — lifted from DO `template.py` `_auto_pair` and generalised to REST.

    create X  ⇒  GET <collection url>/<returned id>
    update X  ⇒  GET <same url>                  (PATCH/PUT already named the record)

Compares the id and every intended field the fetched record also carries. Principle kept from DO:
*a wrong guess can only make a write read as unverified — never as verified* — and here, a guess that
finds nothing to compare is only `acknowledged` (exists), never `verified`.

Reads go through the customer's `http_get(url, params)` (pass-through auth) or a `lookup(descriptor, id)`.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from attest.descriptor import ActionDescriptor
from attest.verify.ladder import ReadBackDriver
from attest.verify.match import MatchReport, compare_overlap
from attest.verify.readers import HttpReader, ReadBackError, build
from attest.verify.refs import first_id

Lookup = Callable[[ActionDescriptor, str], Any]


class ConventionDriver(ReadBackDriver):
    name = "convention"

    def __init__(self, http_get: Any = None, *, lookup: Lookup | None = None):
        self.reader: HttpReader | None = build("http", http_get) if http_get is not None else None  # type: ignore[assignment]
        self.lookup = lookup

    def supports(self, d: ActionDescriptor) -> bool:
        if d.verb not in ("create", "update", "upload", "write"):
            return False
        if self.lookup is not None:
            return True
        return self.reader is not None and bool(d.extra.get("url"))

    @staticmethod
    def read_url(d: ActionDescriptor, result: Any) -> str | None:
        url = str(d.extra.get("url") or "").split("?")[0].rstrip("/")
        if not url:
            return None
        method = str(d.extra.get("method") or "POST").upper()
        rid = first_id(result)
        if method == "POST" and d.verb in ("create", "upload", "write"):
            return f"{url}/{rid}" if rid else None
        return url  # PATCH/PUT/POST-to-id: the write's own URL names the record

    def fetch(self, d: ActionDescriptor, result: Any) -> Any:
        rid = first_id(result) or first_id(d.params, "id")
        if self.lookup is not None:
            return self.lookup(d, rid) if rid else None
        url = self.read_url(d, result)
        if not url or self.reader is None:
            return None
        try:
            return self.reader.get(url)
        except ReadBackError:
            raise

    def compare(self, d: ActionDescriptor, fetched: Any) -> MatchReport:
        r = MatchReport(matched=True)
        if not isinstance(fetched, dict):
            r.check("record:exists", fetched is not None)
            return r
        want_id = first_id(d.result) or first_id(d.params, "id")
        got_id = first_id(fetched)
        if want_id and got_id:
            r.field_("id", want_id, got_id, str(want_id) == str(got_id))
        compare_overlap(r, d.params, fetched)
        if r.compared == 0:
            r.check("record:exists", True)
            r.notes.append("existence only — no intended field present in the read-back")
        return r
