"""attest-mcp — a stdio MCP proxy. Put it between Claude Code / Cursor / any MCP client and the real server:

    { "mcpServers": { "gmail": { "command": "attest-mcp",
                                 "args": ["--upstream", "npx -y @modelcontextprotocol/server-gmail",
                                          "--server", "gmail", "--mode", "block"] } } }

Every `tools/call` is normalized by tool name (`gmail_send_message` ⇒ gmail / send), decided, gated,
forwarded to the upstream server, verified (MCP tool-pair read-back: `create_issue` ⇒ `get_issue`),
and recorded. `tools/list` gains one tool, `attest_resume`, for pending mode.

Modes:  block    the call waits for a human (console is not available on stdio — use the web inbox /
                 Slack via `attest serve`); `--timeout` seconds
        pending  the call returns {"status": "pending_confirmation", "resume_token"}; the agent calls
                 `attest_resume` after a human decided in the inbox / Slack / CLI
        auto     approve everything (dev only)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import sys
from typing import Any

from attest.core import Attest
from attest.descriptor import ActionDescriptor
from attest.exceptions import ActionPending, ActionRefused, ActionRejected
from attest.gate import AutoGate, StoreGate
from attest.gate.store import PendingStore
from attest.ledger import SqliteLedger
from attest.policy import PolicyEngine
from attest.registry import detect
from attest.verify.ladder import ReadBackDriver
from attest.verify.match import MatchReport, compare_overlap
from attest.verify.refs import first_id

RESUME_TOOL = {
    "name": "attest_resume",
    "description": "Resume an action that Attest parked for human confirmation. Pass the resume_token you were "
                   "given; if the human approved, the original tool call is executed now and its result returned.",
    "inputSchema": {"type": "object", "properties": {"resume_token": {"type": "string"}}, "required": ["resume_token"]},
}


def _text_result(obj: Any, *, is_error: bool = False) -> dict[str, Any]:
    text = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def result_value(mcp_result: Any) -> Any:
    """What the ack / read-back drivers should judge: structuredContent, else parsed text content, else raw."""
    if not isinstance(mcp_result, dict):
        return mcp_result
    if mcp_result.get("isError"):
        texts = [c.get("text", "") for c in mcp_result.get("content") or [] if c.get("type") == "text"]
        return {"error": " ".join(texts)[:300] or "tool error"}
    if isinstance(mcp_result.get("structuredContent"), dict):
        return mcp_result["structuredContent"]
    texts = [c.get("text", "") for c in mcp_result.get("content") or [] if c.get("type") == "text"]
    joined = "\n".join(texts).strip()
    if joined:
        try:
            return json.loads(joined)
        except json.JSONDecodeError:
            return joined
    return mcp_result


class McpPairDriver(ReadBackDriver):
    """MCP tool-pair read-back (doc 03 §4 #3): `create_X` / `update_X` ⇒ `get_X` on the same server, when the
    getter takes exactly one required id-like argument. Same rule as DO's `_auto_pair`."""

    name = "mcp-pair"

    def __init__(self, proxy: Proxy):
        self.proxy = proxy

    def _pair(self, d: ActionDescriptor) -> tuple[str, str] | None:
        tool = d.extra.get("tool_name") or ""
        tokens = tool.replace("-", "_").split("_")
        if d.verb not in ("create", "update", "write") or len(tokens) < 2:
            return None
        rest = "_".join(tokens[1:]) if tokens[0] in ("create", "update", "add", "new", "upsert", "post") else None
        if not rest:
            for i, t in enumerate(tokens):
                if t in ("create", "update", "add", "new", "upsert"):
                    rest = "_".join(tokens[:i] + tokens[i + 1:])
                    break
        if not rest:
            return None
        prefixed = f"{tokens[0]}_get_{rest[len(tokens[0]) + 1:]}" if rest.startswith(tokens[0] + "_") else ""
        for cand in (f"get_{rest}", prefixed, f"fetch_{rest}", f"read_{rest}", f"retrieve_{rest}"):
            getter = self.proxy.tools.get(cand)
            if getter:
                schema = getter.get("inputSchema") or {}
                req = list(schema.get("required") or [])
                if len(req) == 1 and req[0].lower().endswith("id"):
                    return cand, req[0]
        return None

    def supports(self, d: ActionDescriptor) -> bool:
        return self._pair(d) is not None

    def fetch(self, d: ActionDescriptor, result: Any) -> Any:
        pair = self._pair(d)
        if pair is None:
            return None
        getter, arg = pair
        rid = first_id(result) if d.verb == "create" else (d.params.get(arg) or first_id(d.params) or first_id(result))
        if not rid:
            return None
        fut = asyncio.run_coroutine_threadsafe(self.proxy.call_upstream(getter, {arg: rid}), self.proxy.loop)
        out = fut.result(timeout=30)
        if out.get("isError"):
            return None
        return result_value(out)

    def compare(self, d: ActionDescriptor, fetched: Any) -> MatchReport:
        r = MatchReport(matched=True)
        if not isinstance(fetched, dict):
            r.check("record:exists", fetched is not None)
            return r
        want_id, got_id = first_id(d.result), first_id(fetched)
        if want_id and got_id:
            r.field_("id", want_id, got_id, str(want_id) == str(got_id))
        compare_overlap(r, d.params, fetched)
        if r.compared == 0:
            r.check("record:exists", True)
        return r


class Proxy:
    def __init__(self, upstream: list[str], client: Attest, *, server: str | None = None, mode: str = "block",
                 read_back: bool = True):
        self.upstream_cmd, self.at, self.server, self.mode, self.read_back = upstream, client, server, mode, read_back
        self.tools: dict[str, dict[str, Any]] = {}
        self._proc: asyncio.subprocess.Process | None = None
        self._internal: dict[str, asyncio.Future] = {}
        self._list_ids: set[Any] = set()
        self._seq = 0
        self._out_lock = asyncio.Lock()
        self._up_lock = asyncio.Lock()
        self.loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        self._resumables: dict[str, tuple[str, dict[str, Any]]] = {}
        if read_back:
            self.at.drivers.append(McpPairDriver(self))

    # ── plumbing ──────────────────────────────────────────────────────────
    async def run(self, stdin: Any = None, stdout: Any = None) -> None:
        self.loop = asyncio.get_running_loop()
        self._proc = await asyncio.create_subprocess_exec(*self.upstream_cmd, stdin=asyncio.subprocess.PIPE,
                                                          stdout=asyncio.subprocess.PIPE, stderr=sys.stderr)
        reader = stdin or await _stdin_reader()
        self._stdout = stdout or sys.stdout.buffer
        await asyncio.gather(self._pump_client(reader), self._pump_upstream())

    async def _pump_client(self, reader: asyncio.StreamReader) -> None:
        while True:
            line = await reader.readline()
            if not line:
                if self._proc and self._proc.stdin:
                    self._proc.stdin.close()
                break
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            asyncio.create_task(self._from_client(msg))

    async def _pump_upstream(self) -> None:
        assert self._proc and self._proc.stdout
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            await self._from_upstream(msg)

    async def _to_client(self, msg: dict[str, Any]) -> None:
        async with self._out_lock:
            self._stdout.write((json.dumps(msg) + "\n").encode())
            self._stdout.flush()

    async def _to_upstream(self, msg: dict[str, Any]) -> None:
        assert self._proc and self._proc.stdin
        async with self._up_lock:
            self._proc.stdin.write((json.dumps(msg) + "\n").encode())
            await self._proc.stdin.drain()

    async def call_upstream(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        rid = f"attest-{self._seq}"
        fut: asyncio.Future = self.loop.create_future()
        self._internal[rid] = fut
        await self._to_upstream({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                                 "params": {"name": name, "arguments": arguments}})
        resp = await fut
        if "error" in resp:
            return _text_result(resp["error"].get("message", "upstream error"), is_error=True)
        return resp.get("result") or {}

    # ── routing ───────────────────────────────────────────────────────────
    async def _from_upstream(self, msg: dict[str, Any]) -> None:
        mid = msg.get("id")
        if mid in self._internal:
            self._internal.pop(mid).set_result(msg)
            return
        if mid in self._list_ids and "result" in msg:
            self._list_ids.discard(mid)
            tools = list((msg["result"] or {}).get("tools") or [])
            self.tools = {t["name"]: t for t in tools}
            msg["result"]["tools"] = tools + [RESUME_TOOL]
        await self._to_client(msg)

    async def _from_client(self, msg: dict[str, Any]) -> None:
        method = msg.get("method")
        if method == "tools/list" and "id" in msg:
            self._list_ids.add(msg["id"])
            await self._to_upstream(msg)
            return
        if method == "tools/call" and "id" in msg:
            result = await self._tool_call(msg.get("params") or {})
            await self._to_client({"jsonrpc": "2.0", "id": msg["id"], "result": result})
            return
        await self._to_upstream(msg)

    # ── the interception ──────────────────────────────────────────────────
    async def _tool_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name, args = params.get("name") or "", dict(params.get("arguments") or {})
        if name == "attest_resume":
            return await self._resume(str(args.get("resume_token") or ""))
        det = detect(tool_name=name, server=self.server)
        d = ActionDescriptor(system=det.system, verb=det.verb, target=det.target, params=args, agent=self.at.agent,
                             actor=self.at.actor, run_id=self.at.current_run_id(), source="mcp",
                             extra={"tool_name": name, "framework": "mcp", "server": self.server})

        async def execute(p: dict[str, Any]) -> Any:
            out = await self.call_upstream(name, {**args, **{k: v for k, v in p.items() if k in args}})
            self._last_raw = out
            val = result_value(out)
            if isinstance(val, dict) and val.get("error") and out.get("isError"):
                raise RuntimeError(val["error"])
            return val

        try:
            receipt = await self.at.arun_action(d, execute, recognised=det.recognised)
        except ActionPending as e:
            self._resumables[e.resume_token] = (name, args)
            return _text_result({"status": "pending_confirmation", "resume_token": e.resume_token,
                                 "action": d.qualified_name,
                                 "message": "A human must approve this action. Call attest_resume with the "
                                            "resume_token once they have decided."})
        except ActionRefused as e:
            return _text_result(f"attest refused: {'; '.join(e.reasons)}", is_error=True)
        except ActionRejected as e:
            return _text_result(f"attest: a human rejected this action ({e.note or e.approver})", is_error=True)
        except RuntimeError as e:
            return _text_result(str(e), is_error=True)
        raw = getattr(self, "_last_raw", None) or _text_result(receipt.result)
        raw = dict(raw)
        raw.setdefault("_attest", {})
        raw["_attest"] = {"level": receipt.level, "action_id": receipt.descriptor.id, "seq": receipt.entry.seq}
        return raw

    async def _resume(self, token: str) -> dict[str, Any]:
        name_args = self._resumables.get(token)
        row = self.at.store.get(token)
        if row is None:
            return _text_result("unknown resume_token", is_error=True)
        if name_args is None:  # parked by another proxy process: rebuild from the stored descriptor
            stored = row["descriptor"]
            name_args = (stored.get("extra", {}).get("tool_name") or "", stored.get("params") or {})
        name, args = name_args

        async def execute(p: dict[str, Any]) -> Any:
            out = await self.call_upstream(name, {**args, **{k: v for k, v in p.items() if k in args}})
            self._last_raw = out
            return result_value(out)

        try:
            receipt = await self.at.aresume(token, execute)
        except ActionPending:
            return _text_result({"status": "pending_confirmation", "resume_token": token,
                                 "message": "Still waiting for a human decision."})
        except ActionRejected as e:
            return _text_result(f"attest: a human rejected this action ({e.note or e.approver})", is_error=True)
        self._resumables.pop(token, None)
        raw = dict(getattr(self, "_last_raw", None) or _text_result(receipt.result))
        raw["_attest"] = {"level": receipt.level, "action_id": receipt.descriptor.id, "seq": receipt.entry.seq}
        return raw


async def _stdin_reader() -> asyncio.StreamReader:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    return reader


def build(args: argparse.Namespace) -> Proxy:
    ledger = SqliteLedger(args.ledger)
    store = PendingStore(args.ledger)
    notifiers: list[Any] = []
    if args.slack_token and args.slack_channel:
        from attest.gate.slack import SlackNotifier
        notifiers.append(SlackNotifier(args.slack_token, args.slack_channel, inbox_url=args.inbox_url))
    if args.webhook:
        from attest.gate.webhook import WebhookNotifier
        notifiers.append(WebhookNotifier(args.webhook, secret=args.webhook_secret, confirm_url=args.inbox_url))
    if args.mode == "auto":
        gate: Any = AutoGate("approved", approver="attest-mcp --mode auto")
    else:
        gate = StoreGate(store, notifiers=notifiers, wait=(args.mode == "block"), timeout_s=args.timeout)
    policy = PolicyEngine.from_file(args.policy) if args.policy else PolicyEngine.from_env()
    at = Attest(ledger=ledger, gate=gate, policy=policy, store=store, agent=args.agent, actor=args.actor)
    upstream = shlex.split(args.upstream)
    return Proxy(upstream, at, server=args.server, mode=args.mode, read_back=not args.no_read_back)


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="attest-mcp", description="Attest MCP proxy (stdio)")
    ap.add_argument("--upstream", required=True, help="command that starts the real MCP server (stdio)")
    ap.add_argument("--server", help="system name for tools without a prefix (gmail, slack, hubspot …)")
    ap.add_argument("--mode", choices=["block", "pending", "auto"], default="block")
    ap.add_argument("--timeout", type=float, default=900, help="block mode: seconds to wait for a human")
    ap.add_argument("--ledger", default=os.environ.get("ATTEST_LEDGER", ".attest/ledger.sqlite"))
    ap.add_argument("--policy", default=os.environ.get("ATTEST_POLICY"))
    ap.add_argument("--agent", default=os.environ.get("ATTEST_AGENT", "mcp-client"))
    ap.add_argument("--actor", default=os.environ.get("ATTEST_ACTOR"))
    ap.add_argument("--inbox-url", default=os.environ.get("ATTEST_INBOX_URL"))
    ap.add_argument("--slack-token", default=os.environ.get("SLACK_BOT_TOKEN"))
    ap.add_argument("--slack-channel", default=os.environ.get("ATTEST_SLACK_CHANNEL"))
    ap.add_argument("--webhook", default=os.environ.get("ATTEST_WEBHOOK_URL"))
    ap.add_argument("--webhook-secret", default=os.environ.get("ATTEST_WEBHOOK_SECRET"))
    ap.add_argument("--no-read-back", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse(argv)
    proxy = build(args)
    try:
        asyncio.run(proxy.run())
    except KeyboardInterrupt:  # pragma: no cover
        pass


if __name__ == "__main__":  # pragma: no cover
    main()
