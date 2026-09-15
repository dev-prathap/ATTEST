"""Attest Cloud v0 API.

    uvicorn attest_cloud.main:app --port 8400

Auth: `Authorization: Bearer atk_…`. Roles: agent (sink, policy read, confirm create/poll), approver (+ decide),
admin (+ keys, policy write, settings). Bootstrap the first org with `X-Bootstrap-Token`.
"""
from __future__ import annotations

import csv
import io
import json
import os
import urllib.parse
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from attest.descriptor import ActionDescriptor, new_id
from attest.gate import ConfirmDecision, ConfirmRequest
from attest.gate.slack import SlackNotifier, handle_interaction, verify_slack_signature
from attest.gate.webhook import WebhookNotifier
from attest.ledger.exports import eu_ai_act_pack, ietf_jsonl
from attest.ledger.models import LedgerEntry
from attest.policy import PolicyContext, PolicyEngine, load_doc
from attest.policy.yaml_loader import DEFAULT_POLICY_YAML
from attest_cloud import __version__, billing, chain, ops
from attest_cloud.auth import Principal, admin, approver, get_db, new_key, principal
from attest_cloud.db import Agent, ApiKey, ConfirmRow, Database, LedgerRow, Org, Policy
from attest_cloud.store import DbStore

app = FastAPI(title="Attest Cloud", version=__version__)
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("ATTEST_CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])


from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def _lifespan(a: FastAPI):  # pragma: no cover - wiring
    if not hasattr(a.state, "db"):
        a.state.db = Database()
    yield


app.router.lifespan_context = _lifespan
ops.install(app)
ops.install_error_tracking(app)


def configure(db: Database) -> FastAPI:
    app.state.db = db
    return app


# ── schemas ───────────────────────────────────────────────────────────────────
class OrgCreate(BaseModel):
    name: str
    slug: str | None = None
    domain: str | None = None
    admin_name: str = "admin"


class KeyCreate(BaseModel):
    name: str
    role: str = Field(pattern="^(admin|approver|agent)$")


class AgentCreate(BaseModel):
    name: str


class PolicyPut(BaseModel):
    yaml: str


class DecideIn(BaseModel):
    descriptor: dict[str, Any]
    recognised: bool = True


class AttestIn(BaseModel):
    entries: list[dict[str, Any]] | None = None
    entry: dict[str, Any] | None = None


class ConfirmCreate(BaseModel):
    action_id: str
    descriptor: dict[str, Any]
    reasons: list[str] = []
    risk_tier: str = "high"
    approvers: list[str] = []
    approver_members: list[str] = []
    hold: bool = False
    id: str | None = None
    resume_token: str | None = None
    ttl_s: float | None = 86400


class DecideConfirm(BaseModel):
    status: str = Field(pattern="^(approved|rejected|edited)$")
    edits: dict[str, Any] | None = None
    note: str | None = None
    approver: str | None = None


class SettingsPut(BaseModel):
    domain: str | None = None
    nango_url: str | None = None
    nango_secret: str | None = None
    nango_connections: dict[str, dict[str, str]] | None = None
    sso_domains: list[str] | None = None
    sso_admins: list[str] | None = None
    sso_default_role: str | None = Field(default=None, pattern="^(approver|admin|agent)$")
    slack_bot_token: str | None = None
    slack_channel: str | None = None
    slack_signing_secret: str | None = None
    webhook_url: str | None = None
    webhook_secret: str | None = None
    inbox_url: str | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)


def _org_json(o: Org) -> dict[str, Any]:
    return {"id": o.id, "name": o.name, "slug": o.slug, "domain": o.domain, "created_at": o.created_at}


def _key_json(k: ApiKey) -> dict[str, Any]:
    return {"id": k.id, "name": k.name, "role": k.role, "prefix": k.prefix, "created_at": k.created_at,
            "revoked_at": k.revoked_at}


def _entry_json(r: LedgerRow) -> dict[str, Any]:
    return {**r.payload, "seq": r.seq, "prev_hash": r.prev_hash, "hash": r.hash, "payload_hash": r.payload_hash,
            "client_seq": r.client_seq, "client_hash": r.client_hash, "received_at": r.received_at}


# ── health / bootstrap ────────────────────────────────────────────────────────
@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True, "version": __version__}


@app.post("/v1/orgs", status_code=201)
def create_org(body: OrgCreate, request: Request, db: Database = Depends(get_db)) -> dict[str, Any]:
    expected = os.environ.get("ATTEST_CLOUD_BOOTSTRAP_TOKEN")
    with db.session() as s:
        count = s.scalar(select(func.count(Org.id))) or 0
        if expected:
            if request.headers.get("X-Bootstrap-Token") != expected:
                raise HTTPException(401, "bad bootstrap token")
        elif count > 0:
            raise HTTPException(403, "set ATTEST_CLOUD_BOOTSTRAP_TOKEN to create further orgs")
        slug = (body.slug or body.name).lower().strip().replace(" ", "-")
        if s.scalar(select(Org).where(Org.slug == slug)):
            raise HTTPException(409, f"slug {slug!r} taken")
        org = Org(id=new_id("org"), name=body.name, slug=slug, domain=body.domain, settings={})
        s.add(org)
        raw, prefix, h = new_key()
        s.add(ApiKey(id=new_id("key"), org_id=org.id, name=body.admin_name, role="admin", prefix=prefix, key_hash=h))
        s.add(Policy(id=new_id("pol"), org_id=org.id, version=1, yaml=DEFAULT_POLICY_YAML, created_by="bootstrap"))
        s.flush()
        return {"org": _org_json(org), "api_key": raw, "role": "admin"}


@app.get("/v1/me")
def me(p: Principal = Depends(principal)) -> dict[str, Any]:
    return {"org": _org_json(p.org), "key": _key_json(p.key)}


# ── keys & agents ─────────────────────────────────────────────────────────────
@app.post("/v1/keys", status_code=201)
def create_key(body: KeyCreate, p: Principal = Depends(admin), db: Database = Depends(get_db)) -> dict[str, Any]:
    raw, prefix, h = new_key()
    with db.session() as s:
        k = ApiKey(id=new_id("key"), org_id=p.org_id, name=body.name, role=body.role, prefix=prefix, key_hash=h)
        s.add(k)
        s.flush()
        return {**_key_json(k), "api_key": raw}


@app.get("/v1/keys")
def list_keys(p: Principal = Depends(admin), db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    with db.session() as s:
        q = select(ApiKey).where(ApiKey.org_id == p.org_id).order_by(ApiKey.created_at)
        return [_key_json(k) for k in s.scalars(q)]


@app.delete("/v1/keys/{key_id}")
def revoke_key(key_id: str, p: Principal = Depends(admin), db: Database = Depends(get_db)) -> dict[str, Any]:
    with db.session() as s:
        k = s.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.org_id == p.org_id))
        if k is None:
            raise HTTPException(404, "unknown key")
        if k.id == p.key.id:
            raise HTTPException(400, "cannot revoke the key making this request")
        k.revoked_at = datetime.now(UTC)
        return _key_json(k)


def _touch_agent(s, org_id: str, name: str | None, n: int = 1) -> None:
    if not name:
        return
    a = s.scalar(select(Agent).where(Agent.org_id == org_id, Agent.name == name))
    if a is None:
        a = Agent(id=new_id("agt"), org_id=org_id, name=name, actions=0)
        s.add(a)
    a.actions = (a.actions or 0) + n
    a.last_seen_at = datetime.now(UTC)


@app.post("/v1/agents", status_code=201)
def create_agent(body: AgentCreate, p: Principal = Depends(admin), db: Database = Depends(get_db)) -> dict[str, Any]:
    with db.session() as s:
        if s.scalar(select(Agent).where(Agent.org_id == p.org_id, Agent.name == body.name)):
            raise HTTPException(409, "agent exists")
        gate = billing.check_agent_slot(s, s.get(Org, p.org_id), body.name)
        if not gate.ok:
            raise HTTPException(402, gate.reason)
        a = Agent(id=new_id("agt"), org_id=p.org_id, name=body.name)
        s.add(a)
        s.flush()
        return {"id": a.id, "name": a.name, "actions": 0}


@app.get("/v1/agents")
def list_agents(p: Principal = Depends(principal), db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    with db.session() as s:
        rows = s.scalars(select(Agent).where(Agent.org_id == p.org_id).order_by(Agent.name))
        return [{"id": a.id, "name": a.name, "actions": a.actions, "last_seen_at": a.last_seen_at,
                 "created_at": a.created_at} for a in rows]


# ── policy ────────────────────────────────────────────────────────────────────
def _active_policy(s, org_id: str) -> Policy | None:
    q = select(Policy).where(Policy.org_id == org_id, Policy.active.is_(True)).order_by(Policy.version.desc())
    return s.scalar(q)


@app.get("/v1/policy")
def get_policy(p: Principal = Depends(principal), db: Database = Depends(get_db)) -> dict[str, Any]:
    with db.session() as s:
        pol = _active_policy(s, p.org_id)
        if pol is None:
            return {"version": 0, "yaml": DEFAULT_POLICY_YAML, "source": "default"}
        return {"version": pol.version, "yaml": pol.yaml, "updated_at": pol.created_at, "created_by": pol.created_by}


@app.put("/v1/policy")
def put_policy(body: PolicyPut, p: Principal = Depends(admin), db: Database = Depends(get_db)) -> dict[str, Any]:
    try:
        doc = load_doc(body.yaml)
        rules = doc.rules
    except Exception as e:
        raise HTTPException(422, f"invalid policy: {e}") from e
    with db.session() as s:
        cur = _active_policy(s, p.org_id)
        version = (cur.version + 1) if cur else 1
        if cur:
            cur.active = False
        pol = Policy(id=new_id("pol"), org_id=p.org_id, version=version, yaml=body.yaml, created_by=p.name)
        s.add(pol)
        s.flush()
        return {"version": version, "rules": len(rules), "groups": len(doc.groups), "agents": len(doc.agent_rules),
                "updated_at": pol.created_at}


@app.get("/v1/policy/versions")
def policy_versions(p: Principal = Depends(principal), db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    with db.session() as s:
        return [{"version": x.version, "active": x.active, "created_by": x.created_by, "created_at": x.created_at}
                for x in s.scalars(select(Policy).where(Policy.org_id == p.org_id).order_by(Policy.version.desc()))]


@app.post("/v1/decide")
def decide(body: DecideIn, p: Principal = Depends(principal), db: Database = Depends(get_db)) -> dict[str, Any]:
    with db.session() as s:
        pol = _active_policy(s, p.org_id)
        engine = PolicyEngine.from_yaml(pol.yaml if pol else DEFAULT_POLICY_YAML,
                                        PolicyContext(org_domain=lambda: p.org.domain))
    try:
        d = ActionDescriptor.model_validate(body.descriptor)
    except Exception as e:
        raise HTTPException(422, f"bad descriptor: {e}") from e
    out = engine.evaluate(d, recognised=body.recognised).to_dict()
    out["policy_version"] = pol.version if pol else 0
    return out


# ── ledger sink & queries ─────────────────────────────────────────────────────
@app.post("/v1/attest", status_code=201)
def attest(body: AttestIn, p: Principal = Depends(principal), db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    entries = list(body.entries or []) + ([body.entry] if body.entry else [])
    if not entries:
        raise HTTPException(422, "no entries")
    out = []
    with db.chain_lock, db.session() as s:
        for e in entries:
            payload = {k: v for k, v in e.items() if k not in ("seq", "prev_hash", "payload_hash", "hash")}
            if "params" in payload.get("descriptor", {}) or "result" in payload.get("descriptor", {}):
                raise HTTPException(422, "descriptor must not carry raw params/result — hashes and previews only")
            entry_id = str(payload.get("id") or new_id("led"))
            payload["id"] = entry_id
            row, created = chain.append(s, p.org_id, payload, entry_id=entry_id, client_seq=e.get("seq"),
                                        client_hash=e.get("hash"))
            if created:
                org = s.get(Org, p.org_id)
                gate = billing.check_agent_slot(s, org, payload.get("agent") or "")
                if payload.get("agent") and not gate.ok:
                    raise HTTPException(402, gate.reason)
                _touch_agent(s, p.org_id, payload.get("agent"))
            out.append({"id": row.entry_id, "action_id": row.action_id, "seq": row.seq, "hash": row.hash})
    return out


@app.get("/v1/ledger")
def ledger(p: Principal = Depends(principal), db: Database = Depends(get_db), limit: int = Query(50, le=500),
           before_seq: int | None = None, run_id: str | None = None, agent: str | None = None,
           level: str | None = None, system: str | None = None) -> list[dict[str, Any]]:
    q = select(LedgerRow).where(LedgerRow.org_id == p.org_id)
    for col, val in ((LedgerRow.run_id, run_id), (LedgerRow.agent, agent), (LedgerRow.level, level),
                     (LedgerRow.system, system)):
        if val is not None:
            q = q.where(col == val)
    if before_seq is not None:
        q = q.where(LedgerRow.seq < before_seq)
    with db.session() as s:
        return [_entry_json(r) for r in s.scalars(q.order_by(LedgerRow.seq.desc()).limit(limit))]


@app.get("/v1/ledger/verify")
def ledger_verify(p: Principal = Depends(principal), db: Database = Depends(get_db)) -> dict[str, Any]:
    with db.session() as s:
        rep = chain.verify(s, p.org_id)
    return {"ok": rep.ok, "checked": rep.checked, "broken_at": rep.broken_at, "problems": rep.problems}


@app.get("/v1/ledger/stats")
def ledger_stats(p: Principal = Depends(principal), db: Database = Depends(get_db)) -> dict[str, Any]:
    with db.session() as s:
        by_level = dict(s.execute(select(LedgerRow.level, func.count()).where(LedgerRow.org_id == p.org_id)
                                  .group_by(LedgerRow.level)).all())
        by_decision = dict(s.execute(select(LedgerRow.decision, func.count()).where(LedgerRow.org_id == p.org_id)
                                     .group_by(LedgerRow.decision)).all())
        total = s.scalar(select(func.count()).where(LedgerRow.org_id == p.org_id)) or 0
    return {"total": total, "by_level": by_level, "by_decision": by_decision}


@app.get("/v1/export")
def export(p: Principal = Depends(principal), db: Database = Depends(get_db), format: str = "json",
           run_id: str | None = None) -> Response:
    q = select(LedgerRow).where(LedgerRow.org_id == p.org_id)
    if run_id:
        q = q.where(LedgerRow.run_id == run_id)
    with db.session() as s:
        rows = s.scalars(q.order_by(LedgerRow.seq)).all()
        rep = chain.verify(s, p.org_id)
    if format in ("ietf", "jsonl", "eu-ai-act", "eu_ai_act"):
        gate = billing.check_compliance_exports(p.org)
        if not gate.ok:
            raise HTTPException(402, gate.reason)
    if format in ("ietf", "jsonl"):
        return Response(ietf_jsonl([_to_entry(r) for r in rows]), media_type="application/x-ndjson")
    if format in ("eu-ai-act", "eu_ai_act"):
        pack = eu_ai_act_pack([_to_entry(r) for r in rows], system={"org": p.org.slug, "org_name": p.org.name},
                              checkpoints=chain.checkpoints(s0, p.org_id) if (s0 := db.Session()) else [],
                              chain={"ok": rep.ok, "checked": rep.checked, "head": rows[-1].hash if rows else None},
                              signing_key=chain.signing_key(), scope=f"org:{p.org.slug}")
        s0.close()
        return Response(json.dumps(pack, default=str, indent=2), media_type="application/json")
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["seq", "created_at", "run_id", "agent", "actor", "system", "verb", "target", "decision", "confirm",
                    "approver", "level", "hash"])
        for r in rows:
            d, c = r.payload.get("descriptor") or {}, r.payload.get("confirm") or {}
            w.writerow([r.seq, r.payload.get("created_at"), r.run_id, r.agent, r.actor, r.system, r.verb,
                        d.get("target"), r.decision, c.get("status"), c.get("approver"), r.level, r.hash])
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="attest-ledger.csv"'})
    manifest = {"format": "attest-ledger/1", "org": p.org.slug, "exported_at": datetime.now(UTC).isoformat(),
                "entries": len(rows),
                "chain": {"ok": rep.ok, "checked": rep.checked, "head": rows[-1].hash if rows else None}}
    body = json.dumps({"manifest": manifest, "entries": [_entry_json(r) for r in rows]}, default=str, indent=2)
    return Response(body, media_type="application/json")


def _to_entry(r: LedgerRow) -> LedgerEntry:
    e = LedgerEntry.model_validate(r.payload)
    e.seq, e.prev_hash, e.payload_hash, e.hash = r.seq, r.prev_hash, r.payload_hash, r.hash
    return e


@app.post("/v1/ledger/checkpoint", status_code=201)
def ledger_checkpoint(p: Principal = Depends(admin), db: Database = Depends(get_db)) -> dict[str, Any]:
    with db.chain_lock, db.session() as s:
        cp = chain.checkpoint(s, p.org_id, p.org.slug, reason="manual")
        if cp is None:
            raise HTTPException(409, "empty ledger")
        return chain.checkpoints(s, p.org_id)[-1]


@app.get("/v1/ledger/checkpoints")
def ledger_checkpoints(p: Principal = Depends(principal), db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    with db.session() as s:
        return chain.checkpoints(s, p.org_id)


class PruneIn(BaseModel):
    older_than_days: int | None = Field(default=None, ge=1)
    before_seq: int | None = Field(default=None, ge=1)


@app.post("/v1/ledger/prune")
def ledger_prune(body: PruneIn, p: Principal = Depends(admin), db: Database = Depends(get_db)) -> dict[str, Any]:
    """Retention. Uses the org's `retention_days` setting when the body names neither bound."""
    days = body.older_than_days or (p.org.settings or {}).get("retention_days")
    with db.chain_lock, db.session() as s:
        before = body.before_seq
        if before is None:
            if not days:
                raise HTTPException(422, "set older_than_days, before_seq, or the org retention_days setting")
            from datetime import timedelta
            cutoff = datetime.now(UTC) - timedelta(days=int(days))
            last_old = s.scalar(select(func.max(LedgerRow.seq)).where(LedgerRow.org_id == p.org_id,
                                                                     LedgerRow.created_at < cutoff))
            before = (last_old or 0) + 1
        removed = chain.prune(s, p.org_id, p.org.slug, before_seq=before)
        rep = chain.verify(s, p.org_id)
    return {"removed": removed, "chain_ok": rep.ok, "entries": rep.checked}


@app.get("/v1/digest")
def ledger_digest(p: Principal = Depends(principal), db: Database = Depends(get_db), since_hours: float = 24,
                  agent: str | None = None) -> dict[str, Any]:
    from datetime import timedelta

    from attest.digest import digest
    cutoff = datetime.now(UTC) - timedelta(hours=since_hours, days=7)
    q = select(LedgerRow).where(LedgerRow.org_id == p.org_id, LedgerRow.created_at >= cutoff)
    if agent:
        q = q.where(LedgerRow.agent == agent)
    with db.session() as s:
        rows = s.scalars(q.order_by(LedgerRow.seq)).all()
    return digest([_to_entry(r) for r in rows], since_hours=since_hours)


@app.get("/v1/ledger/{action_id}")
def ledger_action(action_id: str, p: Principal = Depends(principal),
                  db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    with db.session() as s:
        rows = s.scalars(select(LedgerRow).where(LedgerRow.org_id == p.org_id, LedgerRow.action_id == action_id)
                         .order_by(LedgerRow.seq)).all()
    if not rows:
        raise HTTPException(404, "unknown action")
    return [_entry_json(r) for r in rows]



# ── confirm ───────────────────────────────────────────────────────────────────
def _notify(s, org: Org, request: ConfirmRequest) -> str:
    st = org.settings or {}
    store = DbStore(s, org.id)
    channels = []
    if st.get("slack_bot_token") and st.get("slack_channel"):
        try:
            notifier = SlackNotifier(st["slack_bot_token"], st["slack_channel"], inbox_url=st.get("inbox_url"))
            notifier.notify(request, store)
            channels.append("slack")
        except Exception as e:  # pragma: no cover - network
            store.set_meta(request.id, slack_error=str(e)[:200])
    if st.get("webhook_url"):
        try:
            notifier = WebhookNotifier(st["webhook_url"], secret=st.get("webhook_secret"),
                                       confirm_url=st.get("inbox_url"))
            notifier.notify(request, store)
            channels.append("webhook")
        except Exception as e:  # pragma: no cover - network
            store.set_meta(request.id, webhook_error=str(e)[:200])
    return "+".join(channels) or "cloud"


@app.post("/v1/confirm", status_code=201)
def confirm_create(body: ConfirmCreate, p: Principal = Depends(principal),
                   db: Database = Depends(get_db)) -> dict[str, Any]:
    try:
        d = ActionDescriptor.model_validate(body.descriptor)
    except Exception as e:
        raise HTTPException(422, f"bad descriptor: {e}") from e
    ids = {**({"id": body.id} if body.id else {}), **({"resume_token": body.resume_token} if body.resume_token else {})}
    members = body.approver_members
    if body.approvers and not members:  # resolve groups from the org policy when the SDK sent names only
        with db.session() as s0:
            pol0 = _active_policy(s0, p.org_id)
        try:
            members = load_doc(pol0.yaml if pol0 else DEFAULT_POLICY_YAML).resolve_approvers(body.approvers)
        except Exception:
            members = list(body.approvers)
    req = ConfirmRequest(action_id=body.action_id, descriptor=d, reasons=body.reasons, risk_tier=body.risk_tier,
                         approvers=body.approvers, hold=body.hold, approver_members=members, channel="cloud", **ids)
    with db.session() as s:
        store = DbStore(s, p.org_id)
        if store.get(req.id):
            return store.get(req.id)  # idempotent re-post
        store.create(req, ttl_s=body.ttl_s)
        org = s.get(Org, p.org_id)
        channel = _notify(s, org, req)
        row = s.scalar(select(ConfirmRow).where(ConfirmRow.id == req.id))
        row.channel = channel
        return store.get(req.id)


@app.get("/v1/confirm")
def confirm_list(p: Principal = Depends(principal), db: Database = Depends(get_db), status: str = "pending",
                 limit: int = Query(100, le=500)) -> list[dict[str, Any]]:
    with db.session() as s:
        store = DbStore(s, p.org_id)
        if status == "pending":
            return store.pending(limit)
        return [r for r in store.recent(limit) if status in ("all", r["status"])]


@app.get("/v1/confirm/{ref}")
def confirm_get(ref: str, p: Principal = Depends(principal), db: Database = Depends(get_db)) -> dict[str, Any]:
    with db.session() as s:
        row = DbStore(s, p.org_id).get(ref)
    if row is None:
        raise HTTPException(404, "unknown request")
    return row


@app.post("/v1/confirm/{ref}/decide")
def confirm_decide(ref: str, body: DecideConfirm, p: Principal = Depends(approver),
                   db: Database = Depends(get_db)) -> dict[str, Any]:
    status = "edited" if body.status == "approved" and body.edits else body.status
    dec = ConfirmDecision(status, body.approver or p.name, body.edits, body.note, channel="cloud")
    with db.session() as s:
        store = DbStore(s, p.org_id)
        row = store.get(ref)
        if row is None:
            raise HTTPException(404, "unknown request")
        allowed = set(row.get("approver_members") or []) | set(row.get("approvers") or [])
        if allowed and p.role != "admin" and not any(a.lower() in (dec.approver or "").lower() for a in allowed):
            raise HTTPException(403, f"this request must be decided by one of: {', '.join(sorted(allowed))}")
        if not store.decide(ref, dec):
            raise HTTPException(409, "already decided")
        return store.get(ref)


@app.post("/slack/interact")
async def slack_interact(request: Request, db: Database = Depends(get_db)) -> dict[str, Any]:
    raw = await request.body()
    form = urllib.parse.parse_qs(raw.decode())
    try:
        payload = json.loads(form.get("payload", ["{}"])[0])
    except json.JSONDecodeError as e:
        raise HTTPException(400, "bad payload") from e
    rid = next((a.get("value") for a in payload.get("actions") or [] if a.get("value")), None)
    with db.session() as s:
        store = DbStore(s, None)
        row = store.get(rid) if rid else None
        if row is None:
            raise HTTPException(404, "unknown request")
        org = s.get(Org, row["org_id"])
        secret = (org.settings or {}).get("slack_signing_secret") or os.environ.get("SLACK_SIGNING_SECRET")
        if secret and not verify_slack_signature(secret, request.headers.get("X-Slack-Request-Timestamp", ""), raw,
                                                 request.headers.get("X-Slack-Signature", "")):
            raise HTTPException(401, "bad slack signature")
        client = None
        tok = (org.settings or {}).get("slack_bot_token")
        if tok:
            from attest.gate.slack import _TokenClient
            client = _TokenClient(tok)
        dec = handle_interaction(payload, DbStore(s, org.id), client)
        return {"ok": True, "decision": dec.to_dict() if dec else None}


# ── server-side verification (P3.3) ───────────────────────────────────────────
class VerifyIn(BaseModel):
    descriptor: dict[str, Any]
    result: Any = None
    record: bool = False  # also append a ledger row (API-only callers that never sink one themselves)


@app.post("/v1/verify")
def verify_action(body: VerifyIn, p: Principal = Depends(principal), db: Database = Depends(get_db)) -> dict[str, Any]:
    from attest_cloud import verify as sv
    with db.session() as s:
        org = s.get(Org, p.org_id)
        settings = dict(org.settings or {})
    rec, available = sv.verify_with_org(settings, body.descriptor, body.result,
                                        fetch=getattr(app.state, "nango_fetch", None))
    out = {**rec.model_dump(mode="json"), "read_back_available": available}
    if body.record:
        from attest.descriptor import short_hash
        from attest.ledger.models import ExecutionRecord, LedgerEntry, preview
        d = ActionDescriptor.model_validate(body.descriptor)
        entry = LedgerEntry.from_descriptor(d, decision="recorded", risk_tier="high")
        entry.execution = ExecutionRecord(status="done",
                                          result_hash=None if body.result is None else short_hash(body.result),
                                          result_preview=preview(body.result))
        entry.verification = rec
        payload = entry.payload()
        with db.chain_lock, db.session() as s:
            row, _created = chain.append(s, p.org_id, payload, entry_id=entry.id, client_seq=None, client_hash=None)
            out["seq"], out["hash"] = row.seq, row.hash
    return out


# ── billing ───────────────────────────────────────────────────────────────────
@app.get("/v1/billing")
def get_billing(p: Principal = Depends(principal), db: Database = Depends(get_db)) -> dict[str, Any]:
    with db.session() as s:
        org = s.get(Org, p.org_id)
        use = billing.usage(s, p.org_id)
        lim = billing.limits(org)
        st = org.settings or {}
    return {"plan": billing.plan_of(org), "limits": lim, "usage": use,
            "verified_remaining": (None if lim["verified_actions"] is None
                                   else max(0, lim["verified_actions"] - use["verified_actions"])),
            "stripe": {"status": st.get("stripe_status"), "subscription": st.get("stripe_subscription"),
                       "last_invoice": st.get("last_invoice")},
            "plans": billing.PLANS}


class CheckoutIn(BaseModel):
    plan: str = Field(pattern="^(team|pro)$")
    success_url: str
    cancel_url: str


@app.post("/v1/billing/checkout")
def billing_checkout(body: CheckoutIn, p: Principal = Depends(admin), db: Database = Depends(get_db)) -> dict[str, Any]:
    with db.session() as s:
        org = s.get(Org, p.org_id)
    try:
        session = billing.checkout_session(org, body.plan, success_url=body.success_url, cancel_url=body.cancel_url)
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    return {"url": session.get("url"), "id": session.get("id")}


class PlanIn(BaseModel):
    plan: str = Field(pattern="^(free|team|pro|enterprise)$")
    overrides: dict[str, Any] | None = None


@app.put("/v1/billing/plan")
def set_plan(body: PlanIn, request: Request, p: Principal = Depends(admin),
             db: Database = Depends(get_db)) -> dict[str, Any]:
    """Operator override (needs the bootstrap token as well) — for enterprise contracts and manual upgrades."""
    expected = os.environ.get("ATTEST_CLOUD_BOOTSTRAP_TOKEN")
    if not expected or request.headers.get("X-Bootstrap-Token") != expected:
        raise HTTPException(403, "plan changes require the operator bootstrap token")
    with db.session() as s:
        org = s.get(Org, p.org_id)
        st = dict(org.settings or {})
        st["plan"] = body.plan
        if body.overrides is not None:
            st["plan_overrides"] = body.overrides
        org.settings = st
        return {"plan": body.plan, "limits": billing.limits(org)}


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request, db: Database = Depends(get_db)) -> dict[str, Any]:
    raw = await request.body()
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(503, "STRIPE_WEBHOOK_SECRET not set")
    if not billing.verify_stripe_signature(secret, request.headers.get("Stripe-Signature", ""), raw):
        raise HTTPException(401, "bad stripe signature")
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(400, "bad payload") from e
    with db.session() as s:
        out = billing.apply_stripe_event(s, event)
    return {"ok": True, **out}


# ── SSO (OIDC) ────────────────────────────────────────────────────────────────
from fastapi.responses import RedirectResponse  # noqa: E402

from attest_cloud import oidc  # noqa: E402


@app.get("/auth/login")
def auth_login(request: Request) -> Any:
    if not oidc.enabled():
        raise HTTPException(503, "SSO is not configured (OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, "
                                 "OIDC_REDIRECT_URI, ATTEST_SESSION_SECRET)")
    state = oidc.state_cookie_value()
    resp = RedirectResponse(oidc.login_url(state, getattr(app.state, "oidc_fetch", None)), status_code=302)
    resp.set_cookie("attest_oidc_state", state, httponly=True, samesite="lax", max_age=600)
    return resp


@app.get("/auth/callback")
def auth_callback(request: Request, code: str = "", state: str = "", db: Database = Depends(get_db)) -> Any:
    if not oidc.enabled():
        raise HTTPException(503, "SSO is not configured")
    if not state or request.cookies.get("attest_oidc_state") != state:
        raise HTTPException(401, "bad state")
    claims = oidc.exchange_code(code, getattr(app.state, "oidc_fetch", None))
    org, role = oidc.resolve_org(db, claims["email"])
    token = oidc.make_session(claims, org.id, role)
    dest = os.environ.get("ATTEST_DASHBOARD_URL", "/")
    resp = RedirectResponse(dest, status_code=302)
    resp.set_cookie(oidc.COOKIE, token, httponly=True, samesite="lax", secure=dest.startswith("https"), max_age=8 * 3600)
    resp.delete_cookie("attest_oidc_state")
    return resp


@app.get("/auth/me")
def auth_me(request: Request) -> dict[str, Any]:
    sess = oidc.read_session(request.cookies.get(oidc.COOKIE))
    if not sess:
        raise HTTPException(401, "no session")
    return {k: v for k, v in sess.items() if k != "nonce"}


@app.post("/auth/logout")
def auth_logout() -> Any:
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(oidc.COOKIE)
    return resp


# ── settings ──────────────────────────────────────────────────────────────────
_SECRET_KEYS = ("slack_bot_token", "slack_signing_secret", "webhook_secret", "nango_secret")


def _settings_json(org: Org) -> dict[str, Any]:
    st = dict(org.settings or {})
    for k in _SECRET_KEYS:
        if st.get(k):
            st[k] = st[k][:6] + "…"
    st["domain"] = org.domain
    st["plan"] = billing.plan_of(org)
    return st


@app.get("/v1/settings")
def get_settings(p: Principal = Depends(admin), db: Database = Depends(get_db)) -> dict[str, Any]:
    with db.session() as s:
        return _settings_json(s.get(Org, p.org_id))


@app.put("/v1/settings")
def put_settings(body: SettingsPut, p: Principal = Depends(admin), db: Database = Depends(get_db)) -> dict[str, Any]:
    with db.session() as s:
        org = s.get(Org, p.org_id)
        st = dict(org.settings or {})
        for k, v in body.model_dump(exclude_none=True).items():
            if k == "domain":
                org.domain = v
            elif k == "retention_days":
                gate = billing.check_retention(org, int(v))
                if not gate.ok:
                    raise HTTPException(402, gate.reason)
                st[k] = v
            else:
                st[k] = v
        org.settings = st
        s.flush()
        return _settings_json(org)
