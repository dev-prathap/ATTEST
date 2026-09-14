# Gates & confirmations

One contract — `Gate.confirm(request) → decision` — several ways to pause.

| mode | gate | what happens on `ask` |
| --- | --- | --- |
| console | `ConsoleGate()` (default) | terminal prompt `y / n / e`; a non-interactive stdin **rejects** |
| block | `StoreGate(wait=True, notifiers=[…])` | request persisted; Slack card / webhook sent; call blocks until decided or `timeout_s` |
| pending | `StoreGate(wait=False)` | raises `ActionPending(resume_token)`; `fn.resume(token)` later |
| interrupt | `InterruptGate()` | LangGraph `interrupt()`; `Command(resume=…)` continues |
| cloud | `Attest.cloud(...)` | the cloud persists + notifies; SDK polls or resumes |
| tests / CI | `AutoGate("approved")`, `ATTEST_AUTO_APPROVE=1` | deterministic |

```python
from attest.gate.slack import SlackNotifier
from attest.gate.webhook import WebhookNotifier
at = Attest(gate=StoreGate(PendingStore(".attest/ledger.sqlite"), notifiers=[
    SlackNotifier("xoxb-…", "#agent-approvals", inbox_url="http://localhost:8321"),
    WebhookNotifier("https://your.app/attest", secret="…")]))
```

## Where decisions come from

- **Slack** — Approve / Reject buttons on the card; the approver's Slack identity lands in the ledger. Wire
  the interaction URL to `POST /slack/interact` on `attest serve` or Attest Cloud (signature-verified).
- **Web inbox** — `attest serve` (local) or the dashboard (cloud): approve, reject, or approve with JSON edits.
- **Webhook** — your UI receives the signed request and answers `POST /confirm/{id}`.
- **CLI** — `attest confirm <id> approve --edits '{"subject": "…"}'`.

Edits change what runs. First decision wins. Timeouts expire the request, which counts as a rejection.
Every decision records `status`, `approver`, `channel`, `decided_at`, `edits`.
