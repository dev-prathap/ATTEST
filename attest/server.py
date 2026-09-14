"""Minimal local web confirm inbox + HTTP API (doc 02 surfaces; P1.3.3 / P1.3.7). Standard library only.

    attest serve --port 8321          # http://127.0.0.1:8321/

  GET  /                          inbox: pending requests with Approve / Reject / Edit
  GET  /api/pending               pending confirm requests
  GET  /api/requests/{id}         one request (id or resume token)
  POST /confirm/{id}              {"status": "approved|rejected|edited", "approver": "…", "edits": {…}, "note": "…"}
  GET  /api/ledger?limit=&run_id= ledger entries (newest first)
  GET  /api/ledger/verify         hash-chain report
  POST /slack/interact            Slack interactivity endpoint (signature-verified when a signing secret is set)

Auth: set `token=` (or ATTEST_SERVER_TOKEN) to require `Authorization: Bearer …` on every API call.
"""
from __future__ import annotations

import html
import json
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from attest.gate import ConfirmDecision
from attest.gate.slack import handle_interaction, verify_slack_signature
from attest.gate.store import PendingStore
from attest.ledger import SqliteLedger

_PAGE = """<!doctype html><meta charset=utf-8><title>Attest inbox</title>
<style>body{font:14px/1.4 system-ui,sans-serif;margin:2rem;max-width:960px;color:#111}
.req{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0}.risk{font-weight:600}
.high,.very_high{color:#b00}.medium{color:#a60}.low{color:#080}pre{background:#f6f6f6;padding:.5rem;overflow:auto}
button{margin-right:.5rem;padding:.4rem .8rem}.ok{background:#e6ffe6}.no{background:#ffe6e6}small{color:#666}
textarea{width:100%;height:4rem;font-family:monospace}</style>
<h1>Attest — confirm inbox</h1><p><small>Pending requests refresh every 3s. Your name is recorded as the approver.</small></p>
<label>Approver <input id=who placeholder="you@company.com"></label>
<div id=list></div>
<script>
const T=%TOKEN%; const H=T?{'Authorization':'Bearer '+T,'Content-Type':'application/json'}:{'Content-Type':'application/json'};
async function load(){const r=await fetch('/api/pending',{headers:H});const items=await r.json();const el=document.getElementById('list');
 if(!items.length){el.innerHTML='<p>Nothing pending.</p>';return}
 el.innerHTML=items.map(x=>`<div class=req id="${x.id}"><b>${esc(x.descriptor.system)}.${esc(x.descriptor.verb)}</b> → <code>${esc(x.descriptor.target||'-')}</code>
 &nbsp; <span class="risk ${x.risk_tier}">${x.risk_tier}</span> &nbsp; target: ${x.descriptor.target_class}<br>
 <small>agent ${esc(x.descriptor.agent||'-')} · actor ${esc(x.descriptor.actor||'-')} · run ${esc(x.descriptor.run_id||'-')} · ${x.requested_at}</small>
 <ul>${x.reasons.map(r=>'<li>'+esc(r)+'</li>').join('')}</ul>
 <pre>${esc(JSON.stringify(x.descriptor.params,null,1))}</pre>
 <textarea id="e-${x.id}" placeholder='optional edits as JSON, e.g. {"subject": "..."}'></textarea><br>
 <button class=ok onclick="go('${x.id}','approved')">Approve</button><button class=no onclick="go('${x.id}','rejected')">Reject</button>
 <small>request ${x.id}</small></div>`).join('')}
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
async function go(id,status){const who=document.getElementById('who').value||'inbox';let edits=null;const raw=document.getElementById('e-'+id).value.trim();
 if(raw){try{edits=JSON.parse(raw)}catch(e){alert('edits must be JSON');return}}
 if(edits&&status==='approved')status='edited';
 await fetch('/confirm/'+id,{method:'POST',headers:H,body:JSON.stringify({status,approver:who,edits})});load()}
load();setInterval(load,3000);
</script>"""


class AttestServer:
    def __init__(self, store: PendingStore | None = None, ledger: SqliteLedger | None = None, *,
                 host: str = "127.0.0.1", port: int = 8321, token: str | None = None,
                 slack_signing_secret: str | None = None, slack_client: Any = None,
                 on_decision: Any = None):
        self.store = store or PendingStore()
        self.ledger = ledger or SqliteLedger(self.store.path if self.store.path != ":memory:" else ":memory:")
        self.host, self.port = host, port
        self.token = token if token is not None else os.environ.get("ATTEST_SERVER_TOKEN")
        self.slack_signing_secret = slack_signing_secret or os.environ.get("SLACK_SIGNING_SECRET")
        self.slack_client, self.on_decision = slack_client, on_decision
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────
    def start(self) -> str:
        server = self
        handler = type("Handler", (_Handler,), {"server_ref": server})
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self.port = self._httpd.server_port
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.url

    def serve_forever(self) -> None:
        self.start()
        try:
            self._thread.join()  # type: ignore[union-attr]
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    # ── operations ────────────────────────────────────────────────────────
    def decide(self, request_id: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if self.store.get(request_id) is None:
            return 404, {"error": "unknown request"}
        dec = ConfirmDecision.from_dict(body, channel="web")
        if dec.status not in ("approved", "rejected", "edited"):
            return 400, {"error": f"status must be approved|rejected|edited, got {dec.status!r}"}
        if not dec.approver:
            dec.approver = body.get("approver") or "web"
        if self.store.decide(request_id, dec):
            if self.on_decision:
                self.on_decision(request_id, dec)
            return 200, {"ok": True, "request": self.store.get(request_id)}
        return 409, {"error": "already decided", "request": self.store.get(request_id)}


class _Handler(BaseHTTPRequestHandler):
    server_ref: AttestServer

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet
        pass

    # ── helpers ───────────────────────────────────────────────────────────
    def _json(self, code: int, body: Any) -> None:
        data = json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _html(self, body: str) -> None:
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _authed(self) -> bool:
        tok = self.server_ref.token
        if not tok:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {tok}"

    # ── routes ────────────────────────────────────────────────────────────
    def do_GET(self) -> None:  # noqa: N802
        s = self.server_ref
        path, _, query = self.path.partition("?")
        q = urllib.parse.parse_qs(query)
        if path == "/":
            return self._html(_PAGE.replace("%TOKEN%", json.dumps(s.token or "")))
        if not self._authed():
            return self._json(401, {"error": "unauthorized"})
        if path == "/api/pending":
            return self._json(200, s.store.pending())
        if path.startswith("/api/requests/"):
            row = s.store.get(path.rsplit("/", 1)[-1])
            return self._json(200 if row else 404, row or {"error": "unknown request"})
        if path == "/api/ledger":
            limit = int(q.get("limit", ["50"])[0])
            run_id = q.get("run_id", [None])[0]
            rows = s.ledger.entries(run_id=run_id, limit=limit, newest_first=True)
            return self._json(200, [{**e.payload(), "seq": e.seq, "hash": e.hash} for e in rows])
        if path == "/api/ledger/verify":
            rep = s.ledger.verify_chain()
            return self._json(200, {"ok": rep.ok, "checked": rep.checked, "broken_at": rep.broken_at,
                                    "problems": rep.problems})
        if path == "/healthz":
            return self._json(200, {"ok": True})
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        s = self.server_ref
        path = self.path.split("?")[0]
        raw = self._body()
        if path == "/slack/interact":
            return self._slack(raw)
        if not self._authed():
            return self._json(401, {"error": "unauthorized"})
        if path.startswith("/confirm/") or path.startswith("/api/requests/") and path.endswith("/confirm"):
            rid = path[len("/confirm/"):] if path.startswith("/confirm/") else path.split("/")[3]
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "body must be JSON"})
            code, out = s.decide(rid, body)
            return self._json(code, out)
        self._json(404, {"error": "not found"})

    def _slack(self, raw: bytes) -> None:
        s = self.server_ref
        if s.slack_signing_secret:
            ok = verify_slack_signature(s.slack_signing_secret, self.headers.get("X-Slack-Request-Timestamp", ""),
                                        raw, self.headers.get("X-Slack-Signature", ""))
            if not ok:
                return self._json(401, {"error": "bad slack signature"})
        form = urllib.parse.parse_qs(raw.decode())
        try:
            payload = json.loads(form.get("payload", ["{}"])[0])
        except json.JSONDecodeError:
            return self._json(400, {"error": "bad payload"})
        dec = handle_interaction(payload, s.store, s.slack_client)
        if dec is not None and s.on_decision:
            rid = (payload.get("actions") or [{}])[0].get("value")
            s.on_decision(rid, dec)
        self._json(200, {"ok": True, "decision": dec.to_dict() if dec else None})


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - CLI glue
    import argparse
    ap = argparse.ArgumentParser("attest serve")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8321)
    ap.add_argument("--ledger", default=os.environ.get("ATTEST_LEDGER", ".attest/ledger.sqlite"))
    a = ap.parse_args(argv)
    srv = AttestServer(PendingStore(a.ledger), SqliteLedger(a.ledger), host=a.host, port=a.port)
    print(f"attest inbox at {srv.url}  (ledger {a.ledger})")
    srv.serve_forever()


__all__ = ["AttestServer", "main"]
_ = html  # keep import for template escaping helpers in future
