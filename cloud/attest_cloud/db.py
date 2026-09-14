from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Org(Base):
    __tablename__ = "org"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    domain: Mapped[str | None] = mapped_column(String(200), nullable=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    keys: Mapped[list[ApiKey]] = relationship(back_populates="org")


class ApiKey(Base):
    __tablename__ = "api_key"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("org.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))  # admin | approver | agent
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    org: Mapped[Org] = relationship(back_populates="keys")


class Agent(Base):
    __tablename__ = "agent"
    __table_args__ = (UniqueConstraint("org_id", "name"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("org.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actions: Mapped[int] = mapped_column(Integer, default=0)


class Policy(Base):
    __tablename__ = "policy"
    __table_args__ = (UniqueConstraint("org_id", "version"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("org.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    yaml: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LedgerRow(Base):
    __tablename__ = "ledger_entry"
    __table_args__ = (UniqueConstraint("org_id", "seq"), UniqueConstraint("org_id", "entry_id"),
                      Index("ix_ledger_org_run", "org_id", "run_id"), Index("ix_ledger_org_agent", "org_id", "agent"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("org.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    entry_id: Mapped[str] = mapped_column(String(40))
    action_id: Mapped[str] = mapped_column(String(40), index=True)
    run_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    system: Mapped[str | None] = mapped_column(String(80), nullable=True)
    verb: Mapped[str | None] = mapped_column(String(20), nullable=True)
    decision: Mapped[str] = mapped_column(String(20))
    level: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    client_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CheckpointRow(Base):
    __tablename__ = "ledger_checkpoint"
    __table_args__ = (UniqueConstraint("org_id", "seq"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("org.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    hash: Mapped[str] = mapped_column(String(64))
    signed_at: Mapped[str] = mapped_column(String(40))
    scope: Mapped[str] = mapped_column(String(80))
    signature: Mapped[str | None] = mapped_column(String(80), nullable=True)
    key_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(40), nullable=True)  # manual | retention | export


class ConfirmRow(Base):
    __tablename__ = "confirm_request"
    __table_args__ = (Index("ix_confirm_org_status", "org_id", "status"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("org.id", ondelete="CASCADE"), index=True)
    resume_token: Mapped[str] = mapped_column(String(40), unique=True)
    action_id: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    channel: Mapped[str | None] = mapped_column(String(40), nullable=True)
    descriptor: Mapped[dict] = mapped_column(JSON)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    risk_tier: Mapped[str] = mapped_column(String(20))
    approvers: Mapped[list] = mapped_column(JSON, default=list)
    hold: Mapped[bool] = mapped_column(Boolean, default=False)
    approver_members: Mapped[list] = mapped_column(JSON, default=list)
    approver: Mapped[str | None] = mapped_column(String(200), nullable=True)
    edits: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── engine / session ──────────────────────────────────────────────────────────
def make_engine(url: str | None = None):
    url = url or os.environ.get("DATABASE_URL", "sqlite:///./attest-cloud.sqlite")
    if url.startswith("sqlite"):
        kw = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            kw["poolclass"] = StaticPool
        engine = create_engine(url, **kw)

        @event.listens_for(engine, "connect")
        def _fk(dbapi_con, _):  # pragma: no cover - sqlite only
            dbapi_con.execute("PRAGMA foreign_keys=ON")
    else:
        engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    return engine


class Database:
    def __init__(self, url: str | None = None):
        self.engine = make_engine(url)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        self.chain_lock = threading.Lock()  # per-process guard; Postgres additionally uses SELECT … FOR UPDATE
        self.is_sqlite = self.engine.dialect.name == "sqlite"

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self.Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()
