"""HubSpot — new field-comparing recipe (DO had three create-only existence pairs).

create / update contact | deal | company | ticket | <any object type>
    GET crm/v3/objects/{type}/{id}?properties=<intended keys> ⇒ exists, every intended property equal
"""
from __future__ import annotations

from typing import Any

from attest.descriptor import ActionDescriptor
from attest.verify.match import MatchReport, compare_overlap
from attest.verify.readers import HubSpotReader
from attest.verify.recipes import Recipe, register
from attest.verify.refs import first_id

_TYPES = ("contacts", "deals", "companies", "tickets", "products", "line_items", "quotes", "calls", "emails",
          "meetings", "notes", "tasks")
_TYPE_ALIASES = {"contact": "contacts", "deal": "deals", "company": "companies", "ticket": "tickets",
                 "product": "products", "note": "notes", "task": "tasks", "call": "calls", "meeting": "meetings"}


def object_type(d: ActionDescriptor) -> str | None:
    for k in ("object_type", "objectType", "object"):
        if d.params.get(k):
            v = str(d.params[k]).lower()
            return _TYPE_ALIASES.get(v, v)
    t = (d.target or "").lower().replace("-", "_")
    for part in t.replace("/", "_").split("_"):
        if part in _TYPES:
            return part
        if part in _TYPE_ALIASES:
            return _TYPE_ALIASES[part]
    for k in d.params:
        base = k.lower().replace("_id", "").replace("id", "")
        if base in _TYPE_ALIASES:
            return _TYPE_ALIASES[base]
    return None


def intended_properties(d: ActionDescriptor) -> dict[str, Any]:
    props = d.params.get("properties")
    if isinstance(props, dict):
        return props
    skip = {"object_type", "objectType", "object", "id", "object_id", "objectId", "contact_id", "deal_id", "company_id",
            "ticket_id", "associations", "idProperty"}
    return {k: v for k, v in d.params.items() if k not in skip and not isinstance(v, (dict, list))}


def _object_id(d: ActionDescriptor, result: Any) -> str | None:
    for k in ("object_id", "objectId", "id", "contact_id", "deal_id", "company_id", "ticket_id", "record_id"):
        if d.params.get(k):
            return str(d.params[k])
    return first_id(result)


def fetch_object(reader: HubSpotReader, d: ActionDescriptor, result: Any) -> Any:
    ot, oid = object_type(d), _object_id(d, result)
    if not ot or not oid:
        return None
    return reader.object(ot, oid, list(intended_properties(d).keys()))


def compare_object(d: ActionDescriptor, result: Any, obj: dict) -> MatchReport:
    r = MatchReport(matched=True)
    want_id = _object_id(d, result)
    if want_id and obj.get("id") is not None:
        r.field_("id", want_id, obj.get("id"), str(want_id) == str(obj.get("id")))
    compare_overlap(r, intended_properties(d), obj)
    if r.compared == 0:
        r.check("object:exists", True)
    return r


def _applies(d: ActionDescriptor, result: Any) -> bool:
    return object_type(d) is not None


register(Recipe("hubspot.object", "hubspot", ("create", "update", "write"), fetch_object, compare_object,
                when=_applies))
