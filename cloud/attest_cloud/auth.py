from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select

from attest_cloud.db import ApiKey, Database, Org

ROLES = ("admin", "approver", "agent")
_RANK = {"agent": 0, "approver": 1, "admin": 2}


def new_key() -> tuple[str, str, str]:
    """→ (plaintext, prefix, sha256). Plaintext is shown once."""
    raw = "atk_" + secrets.token_urlsafe(32)
    return raw, raw[:12], hashlib.sha256(raw.encode()).hexdigest()


def key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class Principal:
    org: Org
    key: ApiKey

    @property
    def org_id(self) -> str:
        return self.org.id

    @property
    def role(self) -> str:
        return self.key.role

    @property
    def name(self) -> str:
        return self.key.name

    def require(self, role: str) -> None:
        if _RANK[self.role] < _RANK[role]:
            raise HTTPException(403, f"requires role {role} (key has {self.role})")


def get_db(request: Request) -> Database:
    return request.app.state.db


def principal(request: Request, authorization: str | None = Header(default=None),
              db: Database = Depends(get_db)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        from attest_cloud import oidc
        sess = oidc.read_session(request.cookies.get(oidc.COOKIE)) if request.cookies.get(oidc.COOKIE) else None
        if sess:
            with db.session() as s:
                org = s.get(Org, sess["org_id"])
                if org is None:
                    raise HTTPException(401, "session org no longer exists")
                s.expunge(org)
            key = ApiKey(id="sso:" + sess["email"], org_id=org.id, name=sess["email"], role=sess["role"], prefix="sso",
                         key_hash="")
            return Principal(org, key)
        raise HTTPException(401, "missing bearer API key")
    raw = authorization.split(" ", 1)[1].strip()
    with db.session() as s:
        key = s.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash(raw), ApiKey.revoked_at.is_(None)))
        if key is None:
            raise HTTPException(401, "invalid or revoked API key")
        org = s.get(Org, key.org_id)
        assert org is not None
        return Principal(org, key)


def admin(p: Principal = Depends(principal)) -> Principal:
    p.require("admin")
    return p


def approver(p: Principal = Depends(principal)) -> Principal:
    p.require("approver")
    return p
