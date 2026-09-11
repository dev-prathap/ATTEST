# 06 — Build Plan

## Principles
- **Extract, don't invent.** The policy engine, read-back pairs, convention pairing, verb classifier and action-run journal exist in DO; the receipt hashing and stamping discipline exist in DeerFlow. We lift and generalize. What each piece actually contains, and what must be decoupled, is in [notes/do-extraction.md](./notes/do-extraction.md).
- **Universal from day one.** Descriptor + verb detection + L0 floor ship in week 1, before any deep recipe.
- **OSS-first.** The SDK must be genuinely useful with no cloud (local ledger, YAML policy, console confirm).
- **Tests on the trust core.** Policy, verification, and ledger integrity have tests before anything is published.

## What we reuse

All DO paths are under `app/brain/`. Verified against DO commit `df85d52` on 2026-09-12; see [notes/do-extraction.md](./notes/do-extraction.md) for line ranges and gotchas.

| From | Piece | Becomes |
| --- | --- | --- |
| DO `execution/policy.py` | R0–R4 rules, recipient legitimacy (internal / known / unknown), placeholder hold, risk-tier ⇒ confirm. Three SQL lookups (org rule, org domain, known domain) become injected callables. Unknown-external send is hard-coded **Refuse** in DO; Attest classifies the target and lets YAML decide. | `attest.policy` |
| DO `connectors/providers/template.py` `VERIFY_WITH` | **65** declarative read-back pairs (`$.id` / `$params.x` refs). Existence checks only — no field compare. Coverage: M365 25, Zoho CRM 19, Google 11, HubSpot 3 (create only), Linear 3, Slack 2, Notion 2. | `attest.verify` seed recipes |
| DO `connectors/providers/template.py` `_auto_pair` | convention pairing: create/update-X ⇒ get-X when the getter takes one id param | convention driver |
| DO `connectors/providers/google.py` `verify()` | imperative, **field-comparing** read-back for Gmail send/reply/draft/labels, Calendar, Drive, Docs, Contacts — the real L3 model | `attest.verify` Gmail / Calendar / Drive recipes |
| DO `execution/actions.py` | `$.` / `$params.` / `\|default` ref resolver; engine ordering (policy → gate → execute → verify → journal); soft-error detection; loud "read-back did not confirm" summary | `attest.core` patterns |
| DO `connectors/providers/template.py`, `capabilities.py`, `registry.py` | `VERB_MAP` (~70 aliases), `_verb`/`_risk`, `RISK_BY_VERB`, ~30 reviewed verb/risk overrides, `WRITE_VERBS`, `SYSTEM_LABELS` | `attest.registry` |
| DO `schema.sql` | `action_run` row shape (status vocabulary, idempotency key, attempts, result / verification jsonb); `permission` ⇒ one YAML rule form. `ledger_event` has **no hash chain** — decision 12 is new work. | cloud data model |
| DO `app/web` (Better Auth), Nango self-hosted | multi-tenant auth (not yet reviewed); optional read-only verify auth | cloud |
| DeerFlow `tool_receipt.py`, `tool_receipt_middleware.py` | receipt shape (`args_sha256`, `output_sha256`), runtime-owned stamping that is never preserved from a tool, loud failure logging, `wrap_tool_call` middleware pattern for wrapping every LangGraph tool | ledger hashing, honesty rules, LangGraph adapter |
| DeerFlow `receipt_verification.py` | `UNVERIFIED` vocabulary and the "receipts do not validate correctness" disclaimer. (The module itself checks prose citations, not outcomes.) | ledger semantics |

**Not in either codebase (new code):** hash-chained ledger, Slack confirm cards, web inbox, MCP proxy binary (DEER has an MCP *client* only), direct-SDK read-back for Slack and HubSpot (DO runs those through the Nango proxy), HubSpot update read-back, field-level match reports for template-sourced recipes.

## Phase 1 — Universal core + first recipes (weeks 1–4)

| Week | Deliverable |
| --- | --- |
| 1 | `attest` package skeleton; Action Descriptor; recipe registry with verb detection (MCP names, URL patterns, SDK names, heuristics); policy engine (YAML + R0–R4); local SQLite ledger with hash chain; `@attest.action` decorator; `verify=` hook; L0/L1 ladder; console confirm. **Demo:** unknown app → recorded, decided, attested. |
| 2 | Read-back drivers: convention, custom; reviewed recipes for **Gmail, Slack, HubSpot** (L3); pass-through auth; **LangGraph adapter** (wrap all tools). Tests: policy, verify match/mismatch (`unverified`), ledger integrity. |
| 3 | **Slack confirm app** (cards, approve/reject/edit) + web confirm inbox (minimal); async interrupt mode (LangGraph `interrupt`); **OpenAI Agents SDK adapter**; **MCP proxy** with pending/resume. |
| 4 | **Attest Cloud v0**: FastAPI + Postgres, orgs/API keys, ledger sink, confirm inbox, policies sync; Next.js dashboard (ledger, inbox); docs site + quickstart; **OSS launch prep**. |

Exit criteria: one LangGraph agent sends email + updates HubSpot through Attest → Slack approval → `verified` entries with evidence → export. Works with cloud off and on.

## Phase 2 — Depth + reach (weeks 5–8)
- Recipes: Calendar, Drive/Docs/Sheets, Notion, Linear, Microsoft 365; OpenAPI driver; MCP tool-pair detection.
- Policies UI, approver groups, retention; EU AI Act export pack; IETF format.
- Stripe billing (Team / Pro / usage); Slack Marketplace listing.
- Claude Agent SDK + CrewAI + DeerFlow adapters; `verified-actions` skill on marketplaces; MCP `verify` server published.
- Public launch: Show HN, LangChain integration, content series.

## Phase 3 — Scale (weeks 9–12)
- HTTP gateway (REST proxy) for Nango / Composio / Arcade / direct callers.
- TypeScript SDK (Vercel AI SDK, Mastra, LangChain.js).
- Optional Nango cloud auth for server-side verification (API-only / no-code users).
- LLM-assisted recipe generation pipeline (internal, DeerFlow-driven) + open recipe registry.
- Hardening: signed ledger checkpoints, SSO, on-prem ledger option.

## Division of work

| Claude (build) | Founder (own) |
| --- | --- |
| SDK core, adapters, MCP proxy, recipes, tests, cloud API, dashboard, docs, launch drafts | product decisions, DO walkthroughs, GitHub org, domain, Stripe, Slack app registration, launch, community, first 20 customer conversations |

## Not building (until Phase 3 or later)
- Any vendor **write** connector — we never execute.
- Guardrails / content filtering, tracing, prompt security.
- A workflow builder, an agent framework, a connector catalog UI.
- Enterprise sales motion; on-prem before a paying request.
- Anything unrelated: DO platform launch, India MSME product, M&A tooling, skills/report side businesses.

## Prerequisites (day 0)
1. ~~DO repository under version control and pushed~~ — done 2026-09-12, `dev-pratapk/DO` (private).
2. Confirm locked decisions in 07.
3. GitHub org + domain; Slack workspace for testing.
