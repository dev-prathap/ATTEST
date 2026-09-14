"""Plans, allowances and Stripe (P2.4). No Stripe SDK: webhooks are verified with Stripe's `t=…,v1=…` HMAC scheme
and checkout / portal sessions are created with plain HTTPS calls to api.stripe.com when STRIPE_SECRET_KEY is set.

Plans (doc 02 pricing):
  free        OSS-style: 1 agent, 7-day retention, 100 verified actions / month, no compliance exports
  team  $99   3 agents, 30-day retention, 2,000 verified actions / month
  pro   $499  unlimited agents, 365-day retention, 20,000 verified actions / month, IETF + EU AI Act exports
  enterprise  everything; limits set per contract
Usage unit (doc 07 open question, provisional): **verified actions** = ledger rows whose level is verified,
verified-custom or unverified (a check ran). Acknowledged / attested-only rows are free.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from attest_cloud.db import Agent, LedgerRow, Org

PLANS: dict[str, dict[str, Any]] = {
    "free": {"price_usd": 0, "agents": 1, "retention_days": 7, "verified_actions": 100, "compliance_exports": False},
    "team": {"price_usd": 99, "agents": 3, "retention_days": 30, "verified_actions": 2000, "compliance_exports": False},
    "pro": {"price_usd": 499, "agents": None, "retention_days": 365, "verified_actions": 20000,
            "compliance_exports": True},
    "enterprise": {"price_usd": None, "agents": None, "retention_days": None, "verified_actions": None,
                   "compliance_exports": True},
}
BILLABLE_LEVELS = ("verified", "verified-custom", "unverified")


def plan_of(org: Org) -> str:
    return (org.settings or {}).get("plan") or "free"


def limits(org: Org) -> dict[str, Any]:
    base = dict(PLANS[plan_of(org)])
    base.update((org.settings or {}).get("plan_overrides") or {})
    return base


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def usage(s: Session, org_id: str) -> dict[str, Any]:
    since = month_start()
    verified = s.scalar(select(func.count()).where(LedgerRow.org_id == org_id, LedgerRow.received_at >= since,
                                                    LedgerRow.level.in_(BILLABLE_LEVELS))) or 0
    total = s.scalar(select(func.count()).where(LedgerRow.org_id == org_id, LedgerRow.received_at >= since)) or 0
    agents = s.scalar(select(func.count()).where(Agent.org_id == org_id)) or 0
    return {"period_start": since.isoformat(), "verified_actions": verified, "actions": total, "agents": agents}


@dataclass
class Gate:
    ok: bool
    reason: str | None = None


def check_agent_slot(s: Session, org: Org, name: str) -> Gate:
    lim = limits(org)["agents"]
    if lim is None:
        return Gate(True)
    if s.scalar(select(Agent).where(Agent.org_id == org.id, Agent.name == name)):
        return Gate(True)
    n = s.scalar(select(func.count()).where(Agent.org_id == org.id)) or 0
    return Gate(n < lim, None if n < lim else f"plan {plan_of(org)} allows {lim} agent(s); upgrade to add {name!r}")


def check_verified_allowance(s: Session, org: Org, incoming_verified: int) -> Gate:
    lim = limits(org)["verified_actions"]
    if lim is None:
        return Gate(True)
    used = usage(s, org.id)["verified_actions"]
    if used + incoming_verified <= lim:
        return Gate(True)
    return Gate(False, f"plan {plan_of(org)} allows {lim} verified actions per month ({used} used); the entries "
                       "are still recorded, verification is billed as overage")


def check_compliance_exports(org: Org) -> Gate:
    if limits(org)["compliance_exports"]:
        return Gate(True)
    return Gate(False, f"IETF / EU AI Act exports need the Pro plan (current: {plan_of(org)})")


def check_retention(org: Org, days: int) -> Gate:
    lim = limits(org)["retention_days"]
    if lim is None or days <= lim:
        return Gate(True)
    return Gate(False, f"plan {plan_of(org)} allows up to {lim} days of retention")


# ── Stripe ────────────────────────────────────────────────────────────────────
def verify_stripe_signature(secret: str, header: str, body: bytes, *, tolerance_s: int = 300) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    ts, sig = parts.get("t"), parts.get("v1")
    if not ts or not sig:
        return False
    try:
        if abs(time.time() - int(ts)) > tolerance_s:
            return False
    except ValueError:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


PRICE_TO_PLAN_ENV = {"STRIPE_PRICE_TEAM": "team", "STRIPE_PRICE_PRO": "pro"}


def plan_for_price(price_id: str | None) -> str | None:
    for env, plan in PRICE_TO_PLAN_ENV.items():
        if price_id and os.environ.get(env) == price_id:
            return plan
    return None


def apply_stripe_event(s: Session, event: dict[str, Any]) -> dict[str, Any]:
    """Map subscription events onto org.settings.plan. The org is found by `client_reference_id` (checkout)
    or by the stored `stripe_customer` id. Returns what changed."""
    typ = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    org: Org | None = None
    if typ == "checkout.session.completed":
        ref = obj.get("client_reference_id")
        org = s.get(Org, ref) if ref else None
        if org is None:
            return {"ignored": "no org for checkout"}
        st = dict(org.settings or {})
        st["stripe_customer"] = obj.get("customer")
        st["stripe_subscription"] = obj.get("subscription")
        plan = plan_for_price(((obj.get("metadata") or {}).get("price_id")) or (obj.get("metadata") or {}).get("price"))
        if plan:
            st["plan"] = plan
        org.settings = st
        return {"org": org.id, "plan": st.get("plan"), "customer": st["stripe_customer"]}
    customer = obj.get("customer")
    if customer:
        for o in s.scalars(select(Org)):
            if (o.settings or {}).get("stripe_customer") == customer:
                org = o
                break
    if org is None:
        return {"ignored": f"no org for customer {customer}"}
    st = dict(org.settings or {})
    if typ in ("customer.subscription.created", "customer.subscription.updated"):
        items = ((obj.get("items") or {}).get("data") or [])
        price_id = (items[0].get("price") or {}).get("id") if items else None
        plan = plan_for_price(price_id)
        status = obj.get("status")
        if status in ("active", "trialing") and plan:
            st["plan"] = plan
        elif status in ("canceled", "unpaid", "incomplete_expired"):
            st["plan"] = "free"
        st["stripe_subscription"] = obj.get("id")
        st["stripe_status"] = status
    elif typ == "customer.subscription.deleted":
        st["plan"], st["stripe_status"] = "free", "canceled"
    elif typ == "invoice.paid":
        st["last_invoice"] = {"id": obj.get("id"), "amount_paid": obj.get("amount_paid"),
                              "paid_at": (obj.get("status_transitions") or {}).get("paid_at")}
    elif typ == "invoice.payment_failed":
        st["stripe_status"] = "past_due"
    else:
        return {"ignored": typ}
    org.settings = st
    return {"org": org.id, "plan": st.get("plan"), "status": st.get("stripe_status")}


def stripe_call(path: str, form: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - network
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        raise RuntimeError("STRIPE_SECRET_KEY not set")
    data = urllib.parse.urlencode(form, doseq=True).encode()
    req = urllib.request.Request("https://api.stripe.com/v1/" + path, data=data, method="POST",
                                 headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def checkout_session(org: Org, plan: str, *, success_url: str, cancel_url: str) -> dict[str, Any]:  # pragma: no cover
    price = os.environ.get(f"STRIPE_PRICE_{plan.upper()}")
    if not price:
        raise RuntimeError(f"STRIPE_PRICE_{plan.upper()} not set")
    customer = (org.settings or {}).get("stripe_customer")
    return stripe_call("checkout/sessions", {
        "mode": "subscription", "client_reference_id": org.id, "success_url": success_url, "cancel_url": cancel_url,
        "line_items[0][price]": price, "line_items[0][quantity]": 1, "metadata[price_id]": price,
        **({"customer": customer} if customer else {}),
    })
