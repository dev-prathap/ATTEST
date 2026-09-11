# 04 — Architecture

## Layer diagram

```
Customer agent  (LangGraph · OpenAI Agents · Claude SDK · CrewAI · DeerFlow · MCP · REST · no-code)
      │  tool call
      ▼
┌──────────────────────── ATTEST SDK (in the customer's process) ────────────────────────┐
│ entry points: decorator · framework adapter · MCP proxy · HTTP gateway · API client    │
│ 1 normalize → Action Descriptor (recipe registry: system/verb detection)               │
│ 2 DECIDE   → policy engine (local rules + org policies synced from cloud)              │
│ 3 GATE     → confirm request (sync / interrupt / pending) via cloud or webhook         │
│ 4 EXECUTE  → the customer's own tool runs (we never call the vendor to write)          │
│ 5 VERIFY   → read-back (recipe / OpenAPI / convention / custom fn) — local, pass-through│
│ 6 ATTEST   → ledger entry (local SQLite always; cloud when configured)                 │
└─────────────────────────────────────────────────────────────────────────────────────────┘
      │  entries · confirm requests · policy sync
      ▼
┌──────────────────────── ATTEST CLOUD ───────────────────────────────────────────────────┐
│ FastAPI (Python) · Postgres · Redis                                                     │
│ Ledger (hash-chained, per org) · Confirm Inbox · Policies · Agents/API keys · Exports   │
│ Slack app · Web dashboard (Next.js) · Stripe · optional Nango (read-only verify auth)   │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

## SDK (open source, MIT)
- Package `attest` (Python 3.11+). Zero required cloud: local SQLite ledger, YAML policies, console confirm.
- Modules: `descriptor` · `registry` (recipes, verb detection) · `policy` · `gate` (channels, modes) · `verify` (ladder, read-back drivers) · `ledger` (local + cloud sink) · `adapters/` (langgraph, openai_agents, claude_sdk, crewai, deerflow) · `mcp/` (proxy) · `gateway/` (HTTP proxy, phase 2).
- Design rules: no vendor write calls, ever; tokens never leave the process in pass-through mode; every public function is sync and async; typed, tested.

## Cloud
- **API**: `POST /v1/decide`, `POST /v1/confirm/{id}`, `POST /v1/verify`, `POST /v1/attest`, `GET /v1/ledger`, `GET /v1/export`, policies CRUD, agents & keys.
- **Multi-tenant**: org → users (roles: admin, approver, viewer) → agents → API keys. Every query scoped by `org_id`. (Org/auth model lifted from DO's Better Auth setup; can move to WorkOS later.)
- **Confirm inbox**: pending requests with descriptor, reasons, approve/reject/edit; Slack interactive cards mirror it.
- **Policies UI**: the YAML above, editable; versioned; applied on next decision (SDK syncs).
- **Exports**: JSON, CSV, IETF agent-audit-trail draft, EU AI Act event-log pack; signed manifests.

## Data model (core)
```
org, user, agent, api_key
policy            (org, version, yaml, active)
action            (id, org, agent, actor, run_id, descriptor jsonb, params_hash,
                   decision, reasons jsonb, risk_tier, created_at)
confirm_request   (action_id, channel, status, approver, decided_at, edits jsonb)
execution         (action_id, result jsonb, executed_at)
verification      (action_id, level, method, evidence jsonb, matched bool, checked_at)
ledger_entry      (seq, org, action_id, payload_hash, prev_hash, hash, signed_at)
recipe            (system, verb, read_back spec, source: reviewed|convention|openapi|llm|community)
```
Ledger entries are append-only and hash-chained per org; periodic signed checkpoints allow external anchoring later.

## Verification drivers
- **Read-back recipes** for reviewed systems (Gmail, Calendar, Drive/Docs/Sheets, Slack, HubSpot, Notion, Linear, Microsoft 365, Zoho CRM, Salesforce) — lifted from DO's 41 `VERIFY_WITH` pairs and Google deep adapter.
- **Convention driver**: create/update-X ⇒ get-X.
- **OpenAPI driver**: spec-derived read path.
- **Custom driver**: user function.
- Result comparison is field-level with a match report; mismatch ⇒ `unverified`.

## Stack
Python 3.11 (SDK, FastAPI) · Postgres 16 · Redis · Next.js 15 + Tailwind (dashboard) · Slack Bolt · Stripe · Nango (optional) · Docker Compose; Kubernetes later.

## Security posture
- Pass-through by default: no vendor tokens in the cloud.
- Params stored as hashes plus an allow-listed preview; full payloads only with explicit opt-in.
- Confirmation authority is out-of-band (Slack/web identity), never inferred from content.
- Tenant isolation at every query; audit of admin actions in the same ledger.
