# 06 — Build Plan

## Principles
- **Extract, don't invent.** The policy engine, read-back pairs, ledger schema, org/auth model and Nango handling exist in DO; the receipt/verification patterns exist in DeerFlow. We lift and generalize.
- **Universal from day one.** Descriptor + verb detection + L0 floor ship in week 1, before any deep recipe.
- **OSS-first.** The SDK must be genuinely useful with no cloud (local ledger, YAML policy, console confirm).
- **Tests on the trust core.** Policy, verification, and ledger integrity have tests before anything is published.

## What we reuse

| From | Piece | Becomes |
| --- | --- | --- |
| DO `execution/policy.py` | R0–R4 rules, risk tiers, recipient legitimacy, placeholder hold | `attest.policy` |
| DO `execution/actions.py` | 41 reviewed `VERIFY_WITH` read-back pairs; convention pairing per family | `attest.verify` recipes + convention driver |
| DO `connectors/registry.py`, `capabilities.py` | system registry, verb aliasing, risk-by-verb, `WRITE_VERBS` | `attest.registry` |
| DO schema (`ledger_event`, `action_run`, `permission`) | evidence + permission tables | cloud data model |
| DO Better Auth orgs, Nango self-hosted | multi-tenant auth; optional read-only verify auth | cloud |
| DeerFlow `ToolReceiptMiddleware`, `receipt_verification`, acceptance checks | receipts, UNVERIFIED marking discipline | ledger semantics, honesty rules |
| DeerFlow IM channels, MCP client | Slack/Telegram adapter pattern; MCP proxying | confirm channels, MCP proxy |

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
1. DO repository under version control and pushed (Attest's source material).
2. Confirm locked decisions in 07.
3. GitHub org + domain; Slack workspace for testing.
