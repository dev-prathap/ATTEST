"""Microsoft Teams confirm cards via an incoming webhook (P3.6). Teams webhooks cannot call back into a store,
so the card carries Approve / Reject links to the inbox server's one-click endpoints (signed) and a link to the
inbox itself."""
from __future__ import annotations

import json
import urllib.request
from typing import Any

from attest.gate import ConfirmRequest
from attest.gate.links import decision_links


class TeamsNotifier:
    name = "teams"

    def __init__(self, webhook_url: str, *, inbox_url: str, link_secret: str, post: Any = None):
        self.webhook_url, self.inbox_url, self.link_secret, self._post = webhook_url, inbox_url, link_secret, post

    def card(self, request: ConfirmRequest) -> dict[str, Any]:
        d = request.to_dict()
        approve, reject = decision_links(self.inbox_url, request.id, self.link_secret)
        facts = [{"title": "action", "value": d["action"]}, {"title": "target", "value": d["target"] or "-"},
                 {"title": "risk", "value": d["risk_tier"]}, {"title": "agent", "value": d["agent"] or "-"},
                 {"title": "actor", "value": d["actor"] or "-"}, {"title": "params", "value": json.dumps(d["params_preview"])[:300]}]
        return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.4",
            "body": [{"type": "TextBlock", "size": "Medium", "weight": "Bolder", "text": "Attest: confirmation required"},
                     {"type": "FactSet", "facts": facts},
                     {"type": "TextBlock", "wrap": True, "text": "\n".join(f"• {r}" for r in d["reasons"])}],
            "actions": [{"type": "Action.OpenUrl", "title": "Approve", "url": approve},
                        {"type": "Action.OpenUrl", "title": "Reject", "url": reject},
                        {"type": "Action.OpenUrl", "title": "Open inbox", "url": f"{self.inbox_url.rstrip('/')}/#{request.id}"}]}}]}

    def notify(self, request: ConfirmRequest, store: Any) -> None:
        body = json.dumps(self.card(request)).encode()
        if self._post is not None:
            self._post(self.webhook_url, body)
        else:  # pragma: no cover - network
            req = urllib.request.Request(self.webhook_url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=15).close()
        store.set_meta(request.id, teams_webhook=True)
