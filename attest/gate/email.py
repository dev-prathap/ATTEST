"""Email confirm channel (P3.6): plain SMTP, one-click signed Approve / Reject links to the inbox server."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

from attest.gate import ConfirmRequest
from attest.gate.links import decision_links


class EmailNotifier:
    name = "email"

    def __init__(self, to: list[str] | str, *, sender: str, inbox_url: str, link_secret: str, smtp_host: str = "localhost",
                 smtp_port: int = 587, username: str | None = None, password: str | None = None, starttls: bool = True,
                 send: Any = None):
        self.to = [to] if isinstance(to, str) else list(to)
        self.sender, self.inbox_url, self.link_secret = sender, inbox_url, link_secret
        self.smtp = (smtp_host, smtp_port, username, password, starttls)
        self._send = send

    def message(self, request: ConfirmRequest, recipients: list[str]) -> EmailMessage:
        d = request.to_dict()
        approve, reject = decision_links(self.inbox_url, request.id, self.link_secret)
        msg = EmailMessage()
        msg["Subject"] = f"[Attest] Confirm {d['action']} → {d['target'] or '-'} ({d['risk_tier']})"
        msg["From"], msg["To"] = self.sender, ", ".join(recipients)
        lines = [f"An agent wants to run: {d['action']} → {d['target'] or '-'}", f"risk: {d['risk_tier']}   target: {d['target_class']}",
                 f"agent: {d['agent'] or '-'}   actor: {d['actor'] or '-'}   run: {d['run_id'] or '-'}", f"params: {d['params_preview']}",
                 "", *[f"- {r}" for r in d["reasons"]], "", f"Approve: {approve}", f"Reject:  {reject}",
                 f"Edit / details: {self.inbox_url.rstrip('/')}/#{request.id}", "", f"request {request.id}"]
        msg.set_content("\n".join(lines))
        inbox = f"{self.inbox_url.rstrip('/')}/#{request.id}"
        reasons_html = "".join(f"<li>{r}</li>" for r in d["reasons"])
        msg.add_alternative(
            f"<p>An agent wants to run <b>{d['action']}</b> → <code>{d['target'] or '-'}</code> (risk {d['risk_tier']}).</p>"
            f"<ul>{reasons_html}</ul><pre>{d['params_preview']}</pre>"
            f'<p><a href="{approve}">Approve</a> &nbsp; <a href="{reject}">Reject</a> &nbsp; <a href="{inbox}">Edit / details</a></p>'
            f"<p><small>request {request.id}</small></p>", subtype="html")
        return msg

    def notify(self, request: ConfirmRequest, store: Any) -> None:
        recipients = request.approver_members or self.to
        msg = self.message(request, recipients)
        if self._send is not None:
            self._send(msg)
        else:  # pragma: no cover - network
            host, port, user, pw, tls = self.smtp
            with smtplib.SMTP(host, port, timeout=20) as s:
                if tls:
                    s.starttls()
                if user:
                    s.login(user, pw or "")
                s.send_message(msg)
        store.set_meta(request.id, email_to=recipients)
