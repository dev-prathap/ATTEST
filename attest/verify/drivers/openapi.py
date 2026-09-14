"""OpenAPI driver (doc 03 §4 #2): derive the read-back path from a spec instead of guessing by convention.

    drv = OpenApiDriver(spec_dict_or_yaml, http_get, base_url="https://api.vendor.com")
    at = Attest(drivers=[drv], http_get=…)

For a write `POST /v2/leads` ⇒ finds `GET /v2/leads/{leadId}` (one path parameter, same prefix) and reads
`/v2/leads/<returned id>`. For `PATCH /v2/leads/{id}` ⇒ `GET` on the same templated path. Nested collections
(`/orgs/{orgId}/leads`) resolve the outer params from the write's own URL. Compares the id and every intended
field the record carries. Falls back to nothing (never guesses) when the spec has no matching GET.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from attest.descriptor import ActionDescriptor
from attest.verify.drivers.convention import ConventionDriver
from attest.verify.ladder import ReadBackDriver
from attest.verify.match import MatchReport
from attest.verify.readers import HttpReader, build
from attest.verify.refs import first_id

_PARAM = re.compile(r"\{([^}]+)\}")


def _load(spec: Any) -> dict[str, Any]:
    if isinstance(spec, dict):
        return spec
    text = spec
    if isinstance(spec, str) and ("\n" not in spec) and (spec.endswith((".yaml", ".yml", ".json"))):
        from pathlib import Path
        text = Path(spec).read_text()
    import json
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        import yaml
        return yaml.safe_load(text) or {}


def _template_re(path: str) -> re.Pattern:
    return re.compile("^" + _PARAM.sub(r"(?P<\1>[^/]+)", re.escape(path).replace(r"\{", "{").replace(r"\}", "}")) + "$")


class OpenApiDriver(ReadBackDriver):
    name = "openapi"

    def __init__(self, spec: Any, http_get: Any = None, *, base_url: str | None = None):
        self.spec = _load(spec)
        self.reader: HttpReader | None = build("http", http_get) if http_get is not None else None  # type: ignore[assignment]
        servers = self.spec.get("servers") or []
        self.base_url = (base_url or (servers[0].get("url") if servers else "") or "").rstrip("/")
        self.gets: list[tuple[str, re.Pattern, list[str]]] = []
        self.all_paths: list[tuple[str, re.Pattern, set[str]]] = []
        for path, ops in (self.spec.get("paths") or {}).items():
            if not isinstance(ops, dict):
                continue
            params = _PARAM.findall(path)
            self.all_paths.append((path, _template_re(path), {m.lower() for m in ops if m.lower() in
                                                             ("get", "post", "put", "patch", "delete")}))
            if "get" in {m.lower() for m in ops}:
                self.gets.append((path, _template_re(path), params))

    # ── resolution ────────────────────────────────────────────────────────
    def _rel(self, url: str) -> str:
        parts = urlsplit(url if "://" in url else "https://" + url)
        path = parts.path
        if self.base_url:
            bp = urlsplit(self.base_url).path.rstrip("/")
            if bp and path.startswith(bp):
                path = path[len(bp):]
        return path.rstrip("/") or "/"

    def read_path(self, d: ActionDescriptor, result: Any) -> str | None:
        url = str(d.extra.get("url") or "")
        if not url:
            return None
        rel = self._rel(url)
        method = str(d.extra.get("method") or "POST").upper()
        rid = first_id(result) or first_id(d.params, "id")
        # 1. the write's own path is a templated GET (PATCH/PUT /x/{id}, or POST /x/{id}/…)
        for tpl, rx, _params in self.gets:
            if rx.match(rel) and (method != "POST" or "{" in tpl):
                return rel
        # 2. POST /collection ⇒ GET /collection/{one param}
        if rid:
            for tpl, _rx, params in self.gets:
                if len(params) >= 1 and tpl.rsplit("/", 1)[0] == self._templated(rel):
                    filled = tpl.replace("{" + params[-1] + "}", str(rid))
                    return filled.format(**self._outer(rel)) if "{" in filled else filled
        return None

    def _templated(self, rel: str) -> str:
        """Match the write's concrete path to a spec path template (so nested ids collapse to params)."""
        for tpl, rx, _methods in self.all_paths:
            if rx.match(rel):
                return tpl
        return rel

    def _outer(self, rel: str) -> dict[str, str]:
        for _tpl, rx, _methods in self.all_paths:
            m = rx.match(rel)
            if m:
                return m.groupdict()
        return {}

    # ── driver ────────────────────────────────────────────────────────────
    def supports(self, d: ActionDescriptor) -> bool:
        return (self.reader is not None and d.verb in ("create", "update", "upload", "write")
                and bool(d.extra.get("url")))

    def fetch(self, d: ActionDescriptor, result: Any) -> Any:
        path = self.read_path(d, result)
        if not path or self.reader is None:
            return None
        origin = urlsplit(str(d.extra["url"]))
        base = self.base_url or f"{origin.scheme}://{origin.netloc}"
        bp = urlsplit(self.base_url).path.rstrip("/") if self.base_url else ""
        url = base if (bp and path.startswith(bp)) else base + path
        if bp and path.startswith(bp):
            url = f"{urlsplit(self.base_url).scheme}://{urlsplit(self.base_url).netloc}{path}"
        return self.reader.get(url)

    def compare(self, d: ActionDescriptor, fetched: Any) -> MatchReport:
        return ConventionDriver.compare(self, d, fetched)  # type: ignore[arg-type]
