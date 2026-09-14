"""Demo 1 — an app Attest has never seen (doc 03 §4 walkthrough, P1.1.8).

    POST https://api.someweirdcrm.io/v2/leads

No recipe, no connector, no config. The call is normalized (system `someweirdcrm`, verb `create`),
policy applies by verb, the gate asks because `create` is high risk, the customer's own code executes,
and the ledger entry is hash-linked. Verification climbs the ladder with what is available:
  1) nothing but the response id                      ⇒ acknowledged   (L1)
  2) a one-line custom check                          ⇒ verified-custom (L2)
  3) `http_get=` so the convention driver can GET /v2/leads/{id} and compare fields ⇒ verified (L3)

Run:   python examples/unknown_app.py            (answers y/n on the console)
       ATTEST_AUTO_APPROVE=1 python examples/unknown_app.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from attest import Attest, SqliteLedger  # noqa: E402

# ── a fake vendor so the demo needs no network; swap for httpx / requests in real code ──────────
FAKE_DB: dict[str, dict] = {}


def http_post(url: str, json_body: dict) -> dict:
    lead_id = f"L-{990 + len(FAKE_DB) + 1}"
    FAKE_DB[lead_id] = {"id": lead_id, **json_body}
    return {"id": lead_id, "created": True}


def http_get(url: str) -> dict | None:
    return FAKE_DB.get(url.rsplit("/", 1)[-1])


# ── the customer's tool, wrapped ────────────────────────────────────────────────────────────────
at = Attest(ledger=SqliteLedger(":memory:"), agent="lead-agent@v1", actor="ram@acme.com")
at_l3 = Attest(ledger=at.ledger, agent="lead-agent@v1", actor="ram@acme.com",
               http_get=lambda url, params=None: http_get(url))   # pass-through: your HTTP client, your auth


@at.action(method="POST", url="https://api.someweirdcrm.io/v2/leads")
def create_lead(name: str, email: str, source: str = "web") -> dict:
    return http_post("https://api.someweirdcrm.io/v2/leads", {"name": name, "email": email, "source": source})


# the same tool with a one-line custom check ⇒ L2 `verified-custom`
@at.action(method="POST", url="https://api.someweirdcrm.io/v2/leads",
           verify=lambda r, d: (http_get(f"https://api.someweirdcrm.io/v2/leads/{r['id']}") or {}).get("email") == d.params["email"])
def create_lead_checked(name: str, email: str) -> dict:
    return http_post("https://api.someweirdcrm.io/v2/leads", {"name": name, "email": email})


# the same tool with an HTTP getter ⇒ convention read-back GET /v2/leads/{id}, field compare ⇒ L3 `verified`
@at_l3.action(method="POST", url="https://api.someweirdcrm.io/v2/leads")
def create_lead_l3(name: str, email: str) -> dict:
    return http_post("https://api.someweirdcrm.io/v2/leads", {"name": name, "email": email})


if __name__ == "__main__":
    with at.run("demo-unknown-app"):
        try:
            print("1)", create_lead("Arun", "arun@newco.com"))
            print("2)", create_lead_checked("Priya", "priya@newco.com"))
            print("3)", create_lead_l3("Dev", "dev@newco.com"))
        except Exception as e:  # rejected at the gate
            print("stopped:", e)

    print("\n── ledger ──")
    for e in at.ledger.entries():
        d = e.descriptor
        print(f"#{e.seq} {d['system']}.{d['verb']}:{d['target']}  decision={e.decision} confirm={e.confirm.status} "
              f"exec={e.execution.status if e.execution else '-'}  level={e.verification.level}  "
              f"rules={e.rules_fired}  hash={e.hash[:12]}…")
        print("    evidence:", json.dumps(e.verification.evidence))
    print("chain:", at.ledger.verify_chain())
