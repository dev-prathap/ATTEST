"""attest-mcp-server — a standalone MCP server (stdio) that exposes Attest to any MCP client (doc 05 §3):

  attest_decide   evaluate an action against the policy ⇒ act | ask | refuse, risk tier, reasons
  attest_confirm  create a confirm request (inbox / Slack / webhook) and optionally wait for the decision
  attest_record   record an action that already happened (API-only floor): result ⇒ acknowledged / attested-only,
                  or verified=true/false with evidence
  attest_verify   read back an action with the readers configured by env tokens (GMAIL_TOKEN, SLACK_BOT_TOKEN,
                  HUBSPOT_TOKEN, NOTION_TOKEN, LINEAR_API_KEY, GRAPH_TOKEN) ⇒ level + evidence
  attest_ledger   query the local ledger (last N, by run, by level) and verify the chain

Ledger / policy / gate come from the same env as the CLI (ATTEST_LEDGER, ATTEST_POLICY, ATTEST_AUTO_APPROVE).
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from attest.core import Attest
from attest.descriptor import ActionDescriptor
from attest.exceptions import ActionPending, ActionRejected
from attest.gate import ConfirmRequest, StoreGate
from attest.gate.store import PendingStore
from attest.ledger import SqliteLedger
from attest.ledger.models import VerificationRecord
from attest.policy import PolicyEngine
from attest.verify import verify
from attest.verify.drivers.recipe import RecipeDriver

READER_ENV = {"gmail": "GMAIL_TOKEN", "slack": "SLACK_BOT_TOKEN", "hubspot": "HUBSPOT_TOKEN", "notion": "NOTION_TOKEN",
              "linear": "LINEAR_API_KEY", "calendar": "GOOGLE_TOKEN", "drive": "GOOGLE_TOKEN", "docs": "GOOGLE_TOKEN",
              "sheets": "GOOGLE_TOKEN", "outlook": "GRAPH_TOKEN", "teams": "GRAPH_TOKEN"}

_DESC = {"type": "object", "properties": {
    "system": {"type": "string"}, "verb": {"type": "string"}, "target": {"type": "string"},
    "params": {"type": "object"}, "actor": {"type": "string"}, "agent": {"type": "string"},
    "run_id": {"type": "string"}},
    "required": ["system", "verb"]}
_P = _DESC["properties"]

TOOLS = [
    {"name": "attest_decide", "description": "Evaluate an action against the Attest policy before doing it. Returns "
     "decision (act|ask|refuse), risk_tier, reasons, target_class.", "inputSchema": _DESC},
    {"name": "attest_confirm", "description": "Ask a human to confirm an action (web inbox / Slack / webhook). With "
     "wait=true blocks until decided (timeout_s); otherwise returns a request id to poll with attest_confirm_status.",
     "inputSchema": {"type": "object", "properties": {**_P, "reasons": {"type": "array", "items": {"type": "string"}},
                                                      "wait": {"type": "boolean"}, "timeout_s": {"type": "number"}},
                     "required": ["system", "verb"]}},
    {"name": "attest_confirm_status", "description": "Status of a confirm request (id or resume token).",
     "inputSchema": {"type": "object", "properties": {"request_id": {"type": "string"}}, "required": ["request_id"]}},
    {"name": "attest_record", "description": "Record an action that already happened. Pass the tool's result for an "
     "acknowledged/attested-only level, or verified=true/false with evidence.",
     "inputSchema": {"type": "object", "properties": {**_P, "result": {}, "verified": {"type": "boolean"},
                                                      "evidence": {"type": "object"}, "error": {"type": "string"}},
                     "required": ["system", "verb"]}},
    {"name": "attest_verify", "description": "Read back an action from the system of record with the configured "
     "credentials and compare it with the intent. Returns level (verified|acknowledged|unverified|…) and evidence.",
     "inputSchema": {"type": "object", "properties": {**_P, "result": {}},
                     "required": ["system", "verb", "result"]}},
    {"name": "attest_ledger",
     "description": "Query the ledger: last N entries, filtered by run_id / level; verify the chain.",
     "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}, "run_id": {"type": "string"},
                                                      "level": {"type": "string"},
                                                      "verify_chain": {"type": "boolean"}}}},
]


class Server:
    def __init__(self, client: Attest | None = None):
        if client is None:
            ledger = SqliteLedger(os.environ.get("ATTEST_LEDGER", ".attest/ledger.sqlite"))
            store = PendingStore(ledger.path)
            auto = os.environ.get("ATTEST_AUTO_APPROVE")
            if auto is not None:
                from attest.gate import AutoGate
                gate: Any = AutoGate("approved" if auto.lower() in ("1", "true", "yes") else "rejected", approver="env")
            else:
                gate = StoreGate(store, wait=True, timeout_s=float(os.environ.get("ATTEST_CONFIRM_TIMEOUT", "900")))
            readers = {sys_: os.environ[env] for sys_, env in READER_ENV.items() if os.environ.get(env)}
            client = Attest(ledger=ledger, policy=PolicyEngine.from_env(), gate=gate, store=store, readers=readers,
                            agent=os.environ.get("ATTEST_AGENT", "mcp-verify-client"),
                            actor=os.environ.get("ATTEST_ACTOR"))
        self.at = client

    # ── tools ─────────────────────────────────────────────────────────────
    def _descriptor(self, a: dict[str, Any]) -> ActionDescriptor:
        return ActionDescriptor(system=a.get("system", "unknown"), verb=a.get("verb", "write"), target=a.get("target"),
                                params=a.get("params") or {}, actor=a.get("actor") or self.at.actor,
                                agent=a.get("agent") or self.at.agent, run_id=a.get("run_id"), source="mcp-server")

    def decide(self, a: dict[str, Any]) -> dict[str, Any]:
        d = self._descriptor(a)
        return self.at.policy.evaluate(d).to_dict() | {"action": d.qualified_name}

    def confirm(self, a: dict[str, Any]) -> dict[str, Any]:
        d = self._descriptor(a)
        pol = self.at.policy.evaluate(d)
        d.target_class = pol.target_class  # type: ignore[assignment]
        req = ConfirmRequest(d.id, d, a.get("reasons") or pol.reasons, pol.risk_tier, pol.approvers, pol.hold,
                             approver_members=pol.approver_members, channel="mcp-server")
        store = self.at.store
        store.create(req)
        for n in getattr(self.at.gate, "notifiers", []):
            try:
                n.notify(req, store)
            except Exception:  # noqa: BLE001
                pass
        if a.get("wait"):
            dec = store.wait(req.id, float(a.get("timeout_s") or 900), 1.0)
            return {"request_id": req.id, "resume_token": req.resume_token, **dec.to_dict()}
        return {"request_id": req.id, "resume_token": req.resume_token, "status": "pending"}

    def confirm_status(self, a: dict[str, Any]) -> dict[str, Any]:
        dec = self.at.store.decision(str(a.get("request_id") or ""))
        return dec.to_dict() if dec else {"error": "unknown request"}

    def record(self, a: dict[str, Any]) -> dict[str, Any]:
        e = self.at.attest(system=a.get("system", "unknown"), verb=a.get("verb", "write"), target=a.get("target"),
                           params=a.get("params"), result=a.get("result"), verified=a.get("verified"),
                           evidence=a.get("evidence"), error=a.get("error"), actor=a.get("actor"), agent=a.get("agent"),
                           run_id=a.get("run_id"))
        return {"seq": e.seq, "hash": e.hash, "level": e.verification.level, "decision": e.decision}

    def verify_(self, a: dict[str, Any]) -> dict[str, Any]:
        d = self._descriptor(a).with_result(a.get("result"))
        drivers = [self.at.recipes] + ([self.at.convention] if self.at.convention else [])
        rec: VerificationRecord = verify(d, a.get("result"), drivers=drivers)
        supported = self.at.recipes.supports(d) if isinstance(self.at.recipes, RecipeDriver) else False
        return {**rec.model_dump(mode="json"), "read_back_available": supported}

    def ledger(self, a: dict[str, Any]) -> dict[str, Any]:
        rows = self.at.ledger.entries(run_id=a.get("run_id"), level=a.get("level"), limit=int(a.get("limit") or 20),
                                      newest_first=True)
        out: dict[str, Any] = {"entries": [{"seq": e.seq, "action": f"{e.descriptor['system']}.{e.descriptor['verb']}",
                                            "target": e.descriptor.get("target"), "decision": e.decision,
                                            "confirm": e.confirm.status, "level": e.verification.level,
                                            "created_at": e.created_at.isoformat()} for e in rows]}
        if a.get("verify_chain"):
            rep = self.at.ledger.verify_chain()
            out["chain"] = {"ok": rep.ok, "checked": rep.checked, "broken_at": rep.broken_at}
        return out

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        fn = {"attest_decide": self.decide, "attest_confirm": self.confirm,
              "attest_confirm_status": self.confirm_status, "attest_record": self.record,
              "attest_verify": self.verify_, "attest_ledger": self.ledger}.get(name)
        if fn is None:
            return _text({"error": f"unknown tool {name}"}, True)
        try:
            return _text(fn(args))
        except ActionPending as e:
            return _text({"status": "pending_confirmation", "resume_token": e.resume_token})
        except ActionRejected as e:
            return _text({"error": str(e)}, True)
        except Exception as e:  # noqa: BLE001
            return _text({"error": f"{type(e).__name__}: {e}"}, True)

    # ── stdio JSON-RPC ────────────────────────────────────────────────────
    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if method == "initialize":
            result = {"protocolVersion": params.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}},
                      "serverInfo": {"name": "attest", "version": "0.1.0"}}
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
        if method == "tools/call":
            out = self.call(params.get("name", ""), params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": mid, "result": out}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": mid, "result": {}}
        if mid is None:
            return None
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}

    def run(self, stdin: Any = None, stdout: Any = None) -> None:
        inp, out = stdin or sys.stdin, stdout or sys.stdout
        for line in inp:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            resp = self.handle(msg)
            if resp is not None:
                out.write(json.dumps(resp) + "\n")
                out.flush()


def _text(obj: Any, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(obj, default=str)}], "isError": is_error}


def main() -> None:  # pragma: no cover - CLI glue
    Server().run()


if __name__ == "__main__":  # pragma: no cover
    main()
