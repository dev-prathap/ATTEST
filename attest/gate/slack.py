"""Slack confirm cards (doc 02 §2). Post a Block Kit card with Approve / Reject buttons; record the approver's
Slack identity; update the card with the outcome. Edits go through the web inbox (link on the card).

Two halves, both dependency-free (slack_sdk is optional):
  SlackNotifier   posts the card (any client with `chat_postMessage`, or a bot token)
  handle_interaction(payload, store, client)   processes the `block_actions` payload Slack sends back —
                  wire it via attest.server (`POST /slack/interact`, signature-verified) or slack_bolt (`bolt_app`).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.request
from typing import Any

from attest.gate import ConfirmDecision, ConfirmRequest

APPROVE, REJECT = "attest_approve", "attest_reject"


def _api(token: str, method: str, body: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(f"https://slack.com/api/{method}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


class _TokenClient:
    def __init__(self, token: str):
        self.token = token

    def chat_postMessage(self, **kw: Any) -> dict[str, Any]:  # noqa: N802 - slack_sdk naming
        return _api(self.token, "chat.postMessage", kw)

    def chat_update(self, **kw: Any) -> dict[str, Any]:  # noqa: N802
        return _api(self.token, "chat.update", kw)


def blocks_for(request: ConfirmRequest, *, inbox_url: str | None = None) -> list[dict[str, Any]]:
    d = request.to_dict()
    lines = [f"*{d['action']}* → `{d['target'] or '-'}`   risk *{d['risk_tier']}*   target {d['target_class']}",
             f"agent `{d['agent'] or '-'}` · actor `{d['actor'] or '-'}` · run `{d['run_id'] or '-'}`",
             "params: `" + json.dumps(d["params_preview"], default=str)[:300] + f"`  hash `{d['params_hash']}`"]
    lines += [f"• {r}" for r in d["reasons"]]
    if d["approvers"]:
        members = d.get("approver_members") or []
        lines.append("approvers: " + ", ".join(d["approvers"]) + (f" ({', '.join(members)})" if members else ""))
    if d["hold"]:
        lines.append("_needs input fixed before it can proceed (placeholders) — edit in the inbox_")
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": "Attest: confirmation required"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
        {"type": "actions", "block_id": f"attest:{request.id}", "elements": [
            {"type": "button", "action_id": APPROVE, "style": "primary", "value": request.id,
             "text": {"type": "plain_text", "text": "Approve"}},
            {"type": "button", "action_id": REJECT, "style": "danger", "value": request.id,
             "text": {"type": "plain_text", "text": "Reject"}},
        ]},
    ]
    if inbox_url:
        blocks[2]["elements"].append({"type": "button", "action_id": "attest_open_inbox",
                                      "url": f"{inbox_url.rstrip('/')}/#{request.id}",
                                      "text": {"type": "plain_text", "text": "Edit in inbox"}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"request `{request.id}`"}]})
    return blocks


class SlackNotifier:
    name = "slack"

    def __init__(self, client: Any, channel: str, *, inbox_url: str | None = None):
        self.client = _TokenClient(client) if isinstance(client, str) else client
        self.channel, self.inbox_url = channel, inbox_url

    def notify(self, request: ConfirmRequest, store: Any) -> None:
        d = request.descriptor
        resp = self.client.chat_postMessage(channel=self.channel, text=f"Attest: confirm {d.qualified_name}",
                                            blocks=blocks_for(request, inbox_url=self.inbox_url))
        data = resp if isinstance(resp, dict) else getattr(resp, "data", {}) or {}
        if data.get("ok") is False:
            raise RuntimeError(f"slack: {data.get('error')}")
        store.set_meta(request.id, slack_channel=data.get("channel", self.channel), slack_ts=data.get("ts"))


def handle_interaction(payload: dict[str, Any], store: Any, client: Any = None) -> ConfirmDecision | None:
    """Process a Slack `block_actions` payload. Returns the decision recorded, or None when not ours."""
    if payload.get("type") != "block_actions":
        return None
    actions = [a for a in payload.get("actions") or [] if a.get("action_id") in (APPROVE, REJECT)]
    if not actions:
        return None
    action = actions[0]
    request_id = action.get("value") or (action.get("block_id") or "").replace("attest:", "")
    user = payload.get("user") or {}
    approver = user.get("username") or user.get("name") or user.get("id") or "slack-user"
    if user.get("id"):
        approver = f"{approver} ({user['id']})" if approver != user["id"] else approver
    status = "approved" if action["action_id"] == APPROVE else "rejected"
    decision = ConfirmDecision(status, approver, channel="slack")
    first = store.decide(request_id, decision)
    row = store.get(request_id) or {}
    if client is not None and row:
        meta = row.get("meta") or {}
        channel, ts = meta.get("slack_channel") or (payload.get("channel") or {}).get("id"), meta.get("slack_ts")
        ts = ts or (payload.get("message") or {}).get("ts")
        outcome = row.get("status", status)
        who = row.get("approver") or approver
        text = f"{'✅' if outcome in ('approved', 'edited') else '⛔'} *{outcome}* by {who}" + \
               ("" if first else "  _(already decided)_")
        d = row.get("descriptor") or {}
        try:
            client.chat_update(channel=channel, ts=ts, text=f"Attest: {outcome}", blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": (
                    f"*{d.get('system')}.{d.get('verb')}* → `{d.get('target') or '-'}`\n{text}")}},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": f"request `{request_id}`"}]},
            ])
        except Exception:  # cosmetic; the decision is already recorded
            pass
    return decision if first else store.decision(request_id)


def verify_slack_signature(signing_secret: str, timestamp: str, body: bytes, signature: str,
                           *, max_age_s: int = 300) -> bool:
    try:
        if abs(time.time() - int(timestamp)) > max_age_s:
            return False
    except ValueError:
        return False
    base = f"v0:{timestamp}:".encode() + body
    expected = "v0=" + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def bolt_app(store: Any, *, token: str, signing_secret: str, client: Any = None) -> Any:
    """Optional: a slack_bolt App with the button handlers registered (Socket Mode or HTTP — your choice)."""
    from slack_bolt import App

    app = App(token=token, signing_secret=signing_secret)
    web = client or app.client

    @app.action(APPROVE)
    def _approve(ack, body):  # pragma: no cover - needs slack
        ack()
        handle_interaction(body, store, web)

    @app.action(REJECT)
    def _reject(ack, body):  # pragma: no cover - needs slack
        ack()
        handle_interaction(body, store, web)

    return app
