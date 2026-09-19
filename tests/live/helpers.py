"""Shared helpers for the live suite (imported as `from tests.live.helpers import …`)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from attest import Attest, AutoGate, SqliteLedger

LEDGER = SqliteLedger(":memory:")          # one ledger for the whole session, so the report shows every action


def api(method: str, url: str, token: str, body=None, *, headers=None, auth="Bearer") -> dict:
    data = json.dumps(body).encode() if body is not None else None
    h = {"Authorization": f"{auth} {token}".strip(), "Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        pytest.fail(f"{method} {url} → HTTP {e.code}: {detail}", pytrace=False)


def client(system: str, token: str, **kw) -> Attest:
    """A client whose read-back uses the same token the test writes with (pass-through auth)."""
    return Attest(ledger=LEDGER, gate=AutoGate(approver="live-test"), actor="live@test", agent="live-suite",
                  readers={system: token}, **kw)
