# Attest Cloud

Hosted ledger, confirm inbox, policies, agents & API keys. The SDK works fully without it; the cloud adds a
shared, durable record and a team UI.

```python
at = attest.Attest.cloud("https://cloud.example", api_key="atk_…")     # or ATTEST_CLOUD_URL / ATTEST_API_KEY
```

- **Ledger sink** — every entry is appended locally and pushed; if the cloud is unreachable it queues in a
  local outbox and retries. The agent never blocks on the cloud.
- **Policy sync** — the org's active policy is fetched at start; local / default is the fallback.
- **Confirmations** — created in the cloud, which notifies Slack / webhook with the org settings; the SDK polls
  (block) or resumes later (pending).
- **Never** — vendor tokens. Read-back stays in the agent's process.

## Run it

```bash
cd deploy && cp .env.example .env && docker compose up      # Postgres + API :8400 + dashboard :3400
curl -X POST localhost:8400/v1/orgs -H "X-Bootstrap-Token: $ATTEST_CLOUD_BOOTSTRAP_TOKEN" \
     -H "Content-Type: application/json" -d '{"name": "Acme", "domain": "acme.com"}'
```

The response carries the admin API key (shown once). Open the dashboard, paste the key in Settings, create an
`agent` key for the SDK and an `approver` key for teammates.

## API

| | |
| --- | --- |
| `POST /v1/attest` | ledger sink (entries carry hashes and previews only; raw params are rejected) |
| `GET /v1/ledger` · `/v1/ledger/{action_id}` · `/v1/ledger/verify` · `/v1/ledger/stats` · `/v1/export` | queries, chain check, JSON / CSV export |
| `GET /v1/policy` · `PUT /v1/policy` · `/v1/policy/versions` · `POST /v1/decide` | policy sync, versioned edits, server-side decisions |
| `POST /v1/confirm` · `GET /v1/confirm` · `/v1/confirm/{id}` · `POST /v1/confirm/{id}/decide` · `POST /slack/interact` | confirmations |
| `POST /v1/orgs` · `/v1/me` · `/v1/keys` · `/v1/agents` · `/v1/settings` | tenancy |

Roles: `agent` (sink, policy read, confirm create/poll) · `approver` (+ decide) · `admin` (+ keys, policy, settings).
Every query is scoped by the key's org; the hash chain is per org.

## Plans and billing

| plan | agents | retention | verified actions / month | compliance exports |
| --- | --- | --- | --- | --- |
| free | 1 | 7 days | 100 | – |
| team $99 | 3 | 30 days | 2,000 | – |
| pro $499 | unlimited | 365 days | 20,000 | IETF + EU AI Act |
| enterprise | per contract | per contract | per contract | ✓ |

`GET /v1/billing` shows plan, limits, usage and Stripe status. Gates answer `402` with the reason (agent slots,
compliance exports, retention above the plan). The usage unit is a **verified action**: a row whose level is
`verified`, `verified-custom` or `unverified` — acknowledged and attested-only rows are free. Stripe:
`POST /v1/billing/checkout` (needs `STRIPE_SECRET_KEY`, `STRIPE_PRICE_TEAM|PRO`), `POST /stripe/webhook`
(`STRIPE_WEBHOOK_SECRET`; subscription and invoice events update the plan). Operators set plans and overrides
with `PUT /v1/billing/plan` + the bootstrap token.

## Operations

`ATTEST_RATE_LIMIT` requests / minute per key (429 + Retry-After), `SENTRY_DSN` for error tracking (optional
`sentry_sdk`), `deploy/backup.sh` nightly `pg_dump` with 30-day rotation, `ATTEST_SIGNING_KEY` for checkpoints
and manifests. SDK telemetry is **off** unless `ATTEST_TELEMETRY=1`, and then sends counts only.
