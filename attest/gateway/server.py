"""attest-gateway — an outbound HTTP proxy. The agent (or Nango / Composio / Arcade / any HTTP client) points its
base URL at the gateway; every write is decided, gated, forwarded with the caller's own headers, read back with
the same credentials, and recorded.

Addressing (either):
  http://127.0.0.1:8322/https://api.hubapi.com/crm/v3/objects/deals/123      (URL in the path)
  http://127.0.0.1:8322/crm/v3/objects/deals/123  + header  X-Attest-Upstream: https://api.hubapi.com

Reads (GET/HEAD/OPTIONS) pass straight through and are recorded at `attested-only` only when `--record-reads`.
Modes: block (wait for the inbox / Slack, `--timeout`), pending (202 + resume token; `POST /_attest/resume/<token>`),
auto (dev). Refusals / rejections answer 403 with a JSON body; the upstream is never called.

The caller's `Authorization` header is forwarded and reused for read-back (pass-through auth, doc 03 §5):
known hosts get their reviewed recipe (Gmail / Slack / HubSpot / Notion / Linear / Graph …), anything else gets
the convention driver (`GET <url>/<id>`), or the OpenAPI driver when `--openapi spec` is given.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shlex
import threading
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from attest.core import Attest
from attest.descriptor import ActionDescriptor
from attest.exceptions import ActionPending, ActionRefused, ActionRejected
from attest.gate import AutoGate, StoreGate
from attest.gate.store import PendingStore
from attest.ledger import SqliteLedger
from attest.policy import PolicyEngine
from attest.registry import detect
from attest.registry.systems import system_for_host
from attest.verify.readers import ReadBackError, http_get

log = logging.getLogger("attest.gateway")
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding",
       "upgrade", "host", "content-length", "x-attest-upstream", "x-attest-agent", "x-attest-actor", "x-attest-run"}
READ_METHODS = {"GET", "HEAD", "OPTIONS"}


class Upstream:
    """Forwarding + read-back with the caller's headers. Injectable for tests (`send`)."""

    def __init__(self, send: Any = None, timeout: float = 60.0):
        self._send, self.timeout = send, timeout

    def request(self, method: str, url: str, headers: dict[str, str],
                body: bytes | None) -> tuple[int, dict[str, str], bytes]:
        if self._send is not None:
            return self._send(method, url, headers, body)
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 - caller-chosen upstream
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def getter(self, headers: dict[str, str]) -> Any:
        """`http_get(url, params)` for read-back, carrying the caller's Authorization + Accept headers."""
        keep = {k: v for k, v in headers.items() if k.lower() in ("authorization", "accept", "notion-version",
                                                                  "x-api-key", "api-key", "cookie")}

        def get(url: str, params: dict[str, Any] | None = None) -> Any:
            if params:
                url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
            status, _h, raw = self.request("GET", url, {"Accept": "application/json", **keep}, None)
            if status == 404:
                raise ReadBackError("HTTP 404")
            if status >= 400:
                raise ReadBackError(f"GET {url.split('?')[0]} → HTTP {status}")
            try:
                return json.loads(raw) if raw else {}
            except json.JSONDecodeError as e:
                raise ReadBackError("non-JSON response") from e
        return get


class Gateway:
    def __init__(self, client: Attest, *, upstream: Upstream | None = None, record_reads: bool = False,
                 openapi: Any = None, default_upstream: str | None = None):
        self.at, self.upstream, self.record_reads = client, upstream or Upstream(), record_reads
        self.default_upstream = (default_upstream or "").rstrip("/") or None
        self.openapi = openapi
        if openapi is not None and openapi not in self.at.drivers:
            self.at.drivers.insert(0, openapi)  # spec-derived read-back runs before recipes / convention
        self._pending: dict[str, dict[str, Any]] = {}
        self._httpd: ThreadingHTTPServer | None = None
        self.port = 0

    # ── request handling ──────────────────────────────────────────────────
    def resolve(self, path: str, headers: dict[str, str]) -> str | None:
        p = path.lstrip("/")
        if p.startswith(("http://", "https://")):
            return p
        up = headers.get("x-attest-upstream") or self.default_upstream
        return (up.rstrip("/") + "/" + p) if up else None

    def handle(self, method: str, path: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
        lower = {k.lower(): v for k, v in headers.items()}
        if path.startswith("/_attest/"):
            return self._control(method, path, lower, body)
        url = self.resolve(path, lower)
        if not url:
            return _json(400, {"error": "no upstream: put the full URL in the path or send X-Attest-Upstream"})
        fwd = {k: v for k, v in headers.items() if k.lower() not in HOP}
        if method in READ_METHODS:
            status, rh, raw = self.upstream.request(method, url, fwd, None)
            if self.record_reads:
                det = detect(method=method, url=url)
                self.at.attest(system=det.system, verb=det.verb, target=det.target,
                               result={"status": status}, agent=self._agent(lower), actor=lower.get("x-attest-actor"),
                               run_id=lower.get("x-attest-run"))
            return status, _resp_headers(rh), raw

        det = detect(method=method, url=url)
        params = _params_of(body, lower.get("content-type", ""), url)
        d = ActionDescriptor(system=det.system, verb=det.verb, target=det.target, params=params,
                             agent=self._agent(lower), actor=lower.get("x-attest-actor") or self.at.actor,
                             run_id=lower.get("x-attest-run"), source="url",
                             extra={"method": method, "url": url, "framework": "gateway"})
        getter = self.upstream.getter(fwd)
        readers = self._readers(url, lower)

        def execute(p: dict[str, Any]) -> Any:
            out_body = _rebody(body, lower.get("content-type", ""), params, p)
            status, rh, raw = self.upstream.request(method, url, fwd, out_body)
            self._last = (status, rh, raw)
            val = _json_or_text(raw)
            if status >= 400:
                raise UpstreamError(status, val)
            return val if val is not None else {"status": status}

        try:
            receipt = self.at.run_action(d, execute, recognised=det.recognised, readers=readers, http_get=getter)
        except ActionPending as e:
            self._pending[e.resume_token] = {"method": method, "url": url, "headers": fwd, "body": body,
                                             "content_type": lower.get("content-type", ""), "params": params}
            return _json(202, {"status": "pending_confirmation", "resume_token": e.resume_token,
                               "action": d.qualified_name, "resume": f"/_attest/resume/{e.resume_token}"})
        except ActionRefused as e:
            return _json(403, {"error": "attest refused", "reasons": e.reasons, "action": d.qualified_name})
        except ActionRejected as e:
            return _json(403, {"error": "attest: rejected by a human", "note": e.note, "approver": e.approver})
        except UpstreamError:
            status, rh, raw = self._last
            return status, _attest_headers(_resp_headers(rh), self.at.ledger.last()), raw
        status, rh, raw = self._last
        return status, _attest_headers(_resp_headers(rh), receipt.entry), raw

    def _control(self, method: str, path: str, lower: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
        if path == "/_attest/healthz":
            return _json(200, {"ok": True, "pending": len(self._pending)})
        if path.startswith("/_attest/resume/") and method == "POST":
            token = path.rsplit("/", 1)[-1]
            saved = self._pending.get(token)
            if saved is None and self.at.store.get(token) is None:
                return _json(404, {"error": "unknown resume token"})

            def execute(p: dict[str, Any]) -> Any:
                if saved is None:
                    raise RuntimeError("this gateway process did not park the request")
                out_body = _rebody(saved["body"], saved["content_type"], saved["params"], p)
                status, rh, raw = self.upstream.request(saved["method"], saved["url"], saved["headers"], out_body)
                self._last = (status, rh, raw)
                val = _json_or_text(raw)
                if status >= 400:
                    raise UpstreamError(status, val)
                return val if val is not None else {"status": status}

            try:
                readers = self._readers(saved["url"], saved["headers"]) if saved else None
                getter = self.upstream.getter(saved["headers"]) if saved else None
                receipt = self.at.resume(token, execute, readers=readers, http_get=getter)
            except ActionPending:
                return _json(202, {"status": "pending_confirmation", "resume_token": token})
            except ActionRejected as e:
                return _json(403, {"error": "attest: rejected by a human", "note": e.note, "approver": e.approver})
            except UpstreamError:
                status, rh, raw = self._last
                return status, _resp_headers(rh), raw
            self._pending.pop(token, None)
            status, rh, raw = self._last
            return status, _attest_headers(_resp_headers(rh), receipt.entry), raw
        if path == "/_attest/ledger":
            rows = self.at.ledger.entries(limit=50, newest_first=True)
            return _json(200, [{"seq": e.seq, "action": f"{e.descriptor['system']}.{e.descriptor['verb']}",
                                "target": e.descriptor.get("target"), "decision": e.decision,
                                "confirm": e.confirm.status, "level": e.verification.level} for e in rows])
        return _json(404, {"error": "unknown control path"})

    def _agent(self, lower: dict[str, str]) -> str | None:
        return lower.get("x-attest-agent") or self.at.agent

    def _readers(self, url: str, lower: dict[str, str]) -> dict[str, Any] | None:
        auth = lower.get("authorization", "")
        parts = urllib.parse.urlsplit(url)
        system = system_for_host(parts.netloc, parts.path)
        if auth.lower().startswith("bearer ") and system in ("gmail", "slack", "hubspot", "notion", "calendar", "drive",
                                                              "docs", "sheets", "outlook", "teams"):
            return {system: auth.split(" ", 1)[1]}
        if system == "linear" and auth:
            return {"linear": auth}
        return None

    # ── server ────────────────────────────────────────────────────────────
    def start(self, host: str = "127.0.0.1", port: int = 8322) -> str:
        gw = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a: Any) -> None:
                pass

            def _do(self) -> None:
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                status, headers, raw = gw.handle(self.command, self.path, dict(self.headers), body)
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(raw)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _do

        self._httpd = ThreadingHTTPServer((host, port), Handler)
        self.port = self._httpd.server_port
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return f"http://{host}:{self.port}"

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()


class UpstreamError(Exception):
    def __init__(self, status: int, body: Any):
        self.status, self.body = status, body
        super().__init__(f"upstream HTTP {status}")


# ── helpers ───────────────────────────────────────────────────────────────────
def _json(status: int, obj: Any) -> tuple[int, dict[str, str], bytes]:
    return status, {"Content-Type": "application/json"}, json.dumps(obj, default=str).encode()


def _resp_headers(h: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in h.items() if k.lower() not in HOP and k.lower() != "content-encoding"}


def _attest_headers(h: dict[str, str], entry: Any) -> dict[str, str]:
    if entry is not None:
        h["X-Attest-Level"] = entry.verification.level
        h["X-Attest-Seq"] = str(entry.seq)
        h["X-Attest-Decision"] = entry.decision
    return h


def _params_of(body: bytes, content_type: str, url: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if body:
        if "json" in content_type or body[:1] in (b"{", b"["):
            try:
                val = json.loads(body)
                params = val if isinstance(val, dict) else {"body": val}
            except json.JSONDecodeError:
                params = {"body": body[:200].decode(errors="replace")}
        elif "x-www-form-urlencoded" in content_type:
            form = urllib.parse.parse_qs(body.decode(errors="replace"))
            params = {k: v[0] if len(v) == 1 else v for k, v in form.items()}
        else:
            params = {"body_bytes": len(body)}
    q = urllib.parse.urlsplit(url).query
    if q:
        params = {**{k: v[0] if len(v) == 1 else v for k, v in urllib.parse.parse_qs(q).items()}, **params}
    return params


def _rebody(body: bytes, content_type: str, original: dict[str, Any], edited: dict[str, Any]) -> bytes | None:
    """Apply confirm-time edits to a JSON body; other bodies pass through untouched."""
    if not body or edited == original:
        return body or None
    if "json" in content_type or body[:1] == b"{":
        try:
            val = json.loads(body)
        except json.JSONDecodeError:
            return body
        if isinstance(val, dict):
            val.update({k: v for k, v in edited.items() if k in val})
            return json.dumps(val).encode()
    return body


def _json_or_text(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw[:500].decode(errors="replace")


def build(args: argparse.Namespace) -> Gateway:
    ledger = SqliteLedger(args.ledger)
    store = PendingStore(args.ledger)
    notifiers: list[Any] = []
    if args.slack_token and args.slack_channel:
        from attest.gate.slack import SlackNotifier
        notifiers.append(SlackNotifier(args.slack_token, args.slack_channel, inbox_url=args.inbox_url))
    if args.webhook:
        from attest.gate.webhook import WebhookNotifier
        notifiers.append(WebhookNotifier(args.webhook, secret=args.webhook_secret, confirm_url=args.inbox_url))
    gate: Any = AutoGate("approved", approver="attest-gateway --mode auto") if args.mode == "auto" else \
        StoreGate(store, notifiers=notifiers, wait=(args.mode == "block"), timeout_s=args.timeout)
    policy = PolicyEngine.from_file(args.policy) if args.policy else PolicyEngine.from_env()
    at = Attest(ledger=ledger, gate=gate, policy=policy, store=store, agent=args.agent, actor=args.actor)
    openapi = None
    if args.openapi:
        from attest.verify.drivers.openapi import OpenApiDriver
        openapi = OpenApiDriver(args.openapi, http_get=http_get)
    return Gateway(at, record_reads=args.record_reads, openapi=openapi, default_upstream=args.upstream)


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="attest-gateway", description="Attest outbound HTTP gateway")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8322)
    ap.add_argument("--upstream", help="default upstream base URL when the path is relative")
    ap.add_argument("--mode", choices=["block", "pending", "auto"], default="block")
    ap.add_argument("--timeout", type=float, default=900)
    ap.add_argument("--record-reads", action="store_true")
    ap.add_argument("--openapi", help="OpenAPI spec (file or URL) for spec-derived read-back")
    ap.add_argument("--ledger", default=os.environ.get("ATTEST_LEDGER", ".attest/ledger.sqlite"))
    ap.add_argument("--policy", default=os.environ.get("ATTEST_POLICY"))
    ap.add_argument("--agent", default=os.environ.get("ATTEST_AGENT", "http-client"))
    ap.add_argument("--actor", default=os.environ.get("ATTEST_ACTOR"))
    ap.add_argument("--inbox-url", default=os.environ.get("ATTEST_INBOX_URL"))
    ap.add_argument("--slack-token", default=os.environ.get("SLACK_BOT_TOKEN"))
    ap.add_argument("--slack-channel", default=os.environ.get("ATTEST_SLACK_CHANNEL"))
    ap.add_argument("--webhook", default=os.environ.get("ATTEST_WEBHOOK_URL"))
    ap.add_argument("--webhook-secret", default=os.environ.get("ATTEST_WEBHOOK_SECRET"))
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - CLI glue
    args = parse(argv)
    gw = build(args)
    url = gw.start(args.host, args.port)
    print(f"attest gateway at {url}  (mode {args.mode}, ledger {args.ledger})", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        gw.stop()


_ = (HTTPStatus, shlex)
