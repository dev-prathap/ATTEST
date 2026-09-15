"""OIDC login for the dashboard / cloud (P3.5 SSO). Authorization-code flow against any OIDC provider
(Okta, Entra, Google, Auth0, Keycloak; SAML IdPs via their OIDC bridge). A signed session cookie then acts as an
`approver` principal (or `admin` when the email is listed in the org's `sso_admins`).

Env: OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, OIDC_REDIRECT_URI, ATTEST_SESSION_SECRET.
Org resolution: the email's registered domain matches `org.domain` (or `settings.sso_domains`).

  GET  /auth/login            → 302 to the provider
  GET  /auth/callback?code=   → verifies, sets `attest_session`, 302 to ATTEST_DASHBOARD_URL
  GET  /auth/me               → who am I (session)
  POST /auth/logout
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import select

from attest.registry.systems import registered_domain
from attest_cloud.db import Database, Org

COOKIE = "attest_session"


def _cfg() -> dict[str, str]:
    return {k: os.environ.get(k, "") for k in ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_REDIRECT_URI")}


def enabled() -> bool:
    c = _cfg()
    return all(c.values()) and bool(os.environ.get("ATTEST_SESSION_SECRET"))


def discovery(fetch: Any = None) -> dict[str, Any]:
    url = _cfg()["OIDC_ISSUER"].rstrip("/") + "/.well-known/openid-configuration"
    if fetch is not None:
        return fetch("GET", url, None, {})
    with urllib.request.urlopen(url, timeout=15) as r:  # pragma: no cover - network
        return json.loads(r.read())


def login_url(state: str, fetch: Any = None) -> str:
    c, d = _cfg(), discovery(fetch)
    q = urllib.parse.urlencode({"response_type": "code", "client_id": c["OIDC_CLIENT_ID"], "redirect_uri": c["OIDC_REDIRECT_URI"],
                                "scope": "openid email profile", "state": state})
    return d["authorization_endpoint"] + "?" + q


def exchange_code(code: str, fetch: Any = None) -> dict[str, Any]:
    """→ claims from the ID token (signature is checked by the provider round-trip: we call userinfo)."""
    c, d = _cfg(), discovery(fetch)
    body = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code, "redirect_uri": c["OIDC_REDIRECT_URI"],
                                   "client_id": c["OIDC_CLIENT_ID"], "client_secret": c["OIDC_CLIENT_SECRET"]}).encode()
    if fetch is not None:
        tokens = fetch("POST", d["token_endpoint"], body, {"Content-Type": "application/x-www-form-urlencoded"})
        info = fetch("GET", d["userinfo_endpoint"], None, {"Authorization": f"Bearer {tokens['access_token']}"})
    else:  # pragma: no cover - network
        req = urllib.request.Request(d["token_endpoint"], data=body, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            tokens = json.loads(r.read())
        req = urllib.request.Request(d["userinfo_endpoint"], headers={"Authorization": f"Bearer {tokens['access_token']}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            info = json.loads(r.read())
    if not info.get("email"):
        raise HTTPException(401, "identity provider returned no email")
    return info


def _secret() -> bytes:
    s = os.environ.get("ATTEST_SESSION_SECRET")
    if not s:
        raise HTTPException(503, "ATTEST_SESSION_SECRET not set")
    return s.encode()


def make_session(claims: dict[str, Any], org_id: str, role: str, ttl_s: int = 8 * 3600) -> str:
    payload = {"email": claims["email"], "name": claims.get("name"), "org_id": org_id, "role": role,
               "exp": int(time.time()) + ttl_s, "nonce": secrets.token_hex(8)}
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def read_session(cookie: str | None) -> dict[str, Any] | None:
    if not cookie or "." not in cookie:
        return None
    raw, sig = cookie.rsplit(".", 1)
    if not hmac.compare_digest(hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest(), sig):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload


def resolve_org(db: Database, email: str) -> tuple[Org, str]:
    dom = registered_domain(email.split("@")[-1])
    with db.session() as s:
        for org in s.scalars(select(Org)):
            st = org.settings or {}
            domains = {registered_domain(x) for x in ([org.domain] if org.domain else []) + list(st.get("sso_domains") or [])}
            if dom in domains:
                admins = {a.lower() for a in st.get("sso_admins") or []}
                role = "admin" if email.lower() in admins else st.get("sso_default_role", "approver")
                s.expunge(org)
                return org, role
    raise HTTPException(403, f"no organisation accepts sign-ins from {dom}")


def state_cookie_value() -> str:
    return secrets.token_urlsafe(16)


def principal_from_request(request: Request, db: Database) -> dict[str, Any] | None:
    return read_session(request.cookies.get(COOKIE))
