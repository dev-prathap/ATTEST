"""Server-side read-back (P3.3): for API-only / no-code callers whose agent holds no token, the cloud verifies
with a **read-only** connection from a self-hosted Nango (doc 03 §5 mode 3). Org settings:

    nango_url, nango_secret,
    nango_connections: {"gmail": {"provider_config_key": "google-mail", "connection_id": "…"}, …}

Tokens are fetched from Nango per call and never stored. Only reads happen here — the cloud never writes to a
vendor. `POST /v1/verify` takes a descriptor + result and returns a VerificationRecord.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from attest.descriptor import ActionDescriptor
from attest.ledger.models import VerificationRecord
from attest.verify import verify as ladder_verify
from attest.verify.drivers.recipe import RecipeDriver
from attest.verify.readers import ReadBackError


class NangoClient:
    def __init__(self, url: str, secret: str, *, fetch: Any = None):
        self.url, self.secret, self._fetch = url.rstrip("/"), secret, fetch

    def token(self, provider_config_key: str, connection_id: str) -> str:
        if self._fetch is not None:
            data = self._fetch(provider_config_key, connection_id)
        else:  # pragma: no cover - network
            q = urllib.parse.urlencode({"provider_config_key": provider_config_key})
            req = urllib.request.Request(f"{self.url}/connection/{urllib.parse.quote(connection_id)}?{q}",
                                         headers={"Authorization": f"Bearer {self.secret}"})
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = json.loads(r.read())
            except urllib.error.HTTPError as e:
                raise ReadBackError(f"nango: HTTP {e.code}") from e
        creds = (data or {}).get("credentials") or {}
        tok = creds.get("access_token") or creds.get("api_key") or creds.get("token")
        if not tok:
            raise ReadBackError("nango: connection has no access token")
        return str(tok)


def readers_for(settings: dict[str, Any], *, fetch: Any = None) -> dict[str, str]:
    """{system: token} for every configured Nango connection of the org."""
    url, secret = settings.get("nango_url"), settings.get("nango_secret")
    conns = settings.get("nango_connections") or {}
    if not url or not secret or not conns:
        return {}
    client = NangoClient(url, secret, fetch=fetch)
    out: dict[str, str] = {}
    for system, spec in conns.items():
        try:
            out[system] = client.token(spec["provider_config_key"], spec["connection_id"])
        except (ReadBackError, KeyError):
            continue
    return out


def verify_with_org(settings: dict[str, Any], descriptor: dict[str, Any], result: Any, *, fetch: Any = None
                    ) -> tuple[VerificationRecord, bool]:
    d = ActionDescriptor.model_validate(descriptor).with_result(result)
    readers = readers_for(settings, fetch=fetch)
    driver = RecipeDriver(readers)
    available = driver.supports(d)
    rec = ladder_verify(d, result, drivers=[driver] if readers else [])
    if readers and not available and rec.level in ("acknowledged", "attested-only"):
        rec.evidence["detail"] = f"no read-back recipe / connection for {d.system}.{d.verb}; " + \
            str(rec.evidence.get("detail", ""))
    return rec, available
