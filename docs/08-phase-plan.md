# 08 — Phase Plan (detailed split)

Expands 06. Every task has an ID (`P<phase>.<component>.<n>`) so we can track it. Phases are sequential; sub-phases inside Phase 1 are weekly and strictly ordered because each depends on the previous.

```
P0 Prereqs (2 days)
 └─► P1 Universal core + first recipes (4 weeks)   ← critical path, OSS launch at the end
      └─► P2 Depth + reach (4 weeks)               ← cloud paid, marketplaces, public launch
           └─► P3 Scale (4 weeks)                  ← gateway, TypeScript, recipe automation
                └─► P4 Growth (ongoing)            ← partners, enterprise packs, ecosystem
```

Milestones: **M1** first end-to-end verified action (end P1.2) · **M2** OSS launch (end P1) · **M3** first paying team (P2) · **M4** public launch (end P2) · **M5** $10k MRR (P4).

---

## P0 — Prerequisites (day 0–2)

| ID | Task | Owner | Done when |
| --- | --- | --- | --- |
| P0.1 | DO repo: `git init`, `.gitignore` (.env, .fernet_key, .oauth_pkce.json, _ref-*, node_modules, .venv), commit, push to private GitHub | Founder (Claude can run it) | DO is on GitHub |
| P0.2 | ATTEST repo: first commit, private remote | Founder | pushed |
| P0.3 | Confirm locked decisions (07): name, wrapper model, Python-first, Gmail/Slack/HubSpot first | Founder | 07 updated |
| P0.4 | GitHub org, domain, test Slack workspace, test Gmail/HubSpot accounts | Founder | credentials in a local `.env` |
| P0.5 | Claude: read DO `execution/policy.py`, `execution/actions.py` (VERIFY_WITH), `connectors/registry.py`, `connectors/capabilities.py`, `schema.sql` ledger/permission tables end to end; write extraction notes | Claude | `docs/notes/do-extraction.md` |

Exit: repos safe, decisions locked, source material mapped.

---

## P1 — Universal core + first recipes (weeks 1–4) — critical path

Goal: an OSS SDK that works for **any** app on day one, verifies deeply for three, gates via Slack, and has a minimal cloud — ready to launch.

### P1.1 (week 1) — Descriptor, registry, policy, ledger, decorator
Repo layout:
```
attest/
  descriptor.py   registry/{__init__,verbs,mcp_names,url_patterns,sdk_names}.py
  policy/{engine,rules,yaml_loader}.py   ledger/{local_sqlite,hashchain,models}.py
  verify/{ladder,drivers/{custom,ack}}.py   gate/{console}.py   core.py (Attest, @action)
tests/
```

| ID | Task | Source | Done when |
| --- | --- | --- | --- |
| P1.1.1 | `ActionDescriptor` (pydantic): system, verb, target, params, params_hash, actor, agent, run_id, result | 03 §1 | model + tests |
| P1.1.2 | Verb taxonomy + detection: MCP tool-name patterns, REST URL patterns, SDK call names, heuristics; unknown ⇒ `write` | DO `VERB_ALIAS`, `WRITE_VERBS`, registry `systems()` | ≥ 40 pattern tests incl. unknown app |
| P1.1.3 | Policy engine: YAML rules (`match` on descriptor fields, `decision`, `approvers`) + built-in R0–R4 (org rule, acting-on-other's-connection, recipient legitimacy internal/known/unknown, placeholder hold, risk-tier ⇒ confirm) | DO `policy.py` | `PolicyResult{decision, risk_tier, requires_confirm, allow, reasons}`; tests for every rule |
| P1.1.4 | Local ledger: SQLite, append-only, `prev_hash`/`hash` chain, `verify_chain()` | DO `ledger_event` + DeerFlow receipt ids | tamper test (edit a row ⇒ chain breaks) |
| P1.1.5 | `@attest.action(system=, verb=, risk=, verify=)` decorator + `Attest()` client; sync + async | — | decorated function runs decide → (console gate) → execute → verify → ledger |
| P1.1.6 | Verification ladder L0/L1: `attested-only`, `acknowledged` (result has id/status); `verify=` custom ⇒ L2 | 03 §4 | levels recorded |
| P1.1.7 | Console gate (y/n) for local use | — | works without cloud |
| P1.1.8 | **Demo 1 — unknown app**: `POST api.someweirdcrm.io/v2/leads` through the decorator ⇒ recorded, verb `create`, policy applied, L1 | 03 §4 walkthrough | script in `examples/` |

Exit P1.1: `pip install -e .`; any function can be attested; ledger chain verifies; unknown app works.

### P1.2 (week 2) — Read-back verification + LangGraph → **M1**

| ID | Task | Source | Done when |
| --- | --- | --- | --- |
| P1.2.1 | Read-back driver interface: `ReadBack(system, verb) -> (fetch(result) , compare(intent, fetched) -> MatchReport)` | DO `VERIFY_WITH` shape | interface + fake driver tests |
| P1.2.2 | **Convention driver**: create/update-X ⇒ get-X using returned id (REST + SDK) | DO "by convention for every family" | works on the unknown-app demo ⇒ L3 |
| P1.2.3 | **Gmail recipe**: send/reply ⇒ `messages.get` (SENT label, to, subject); label/archive ⇒ label check | DO Google deep adapter | live test with test account |
| P1.2.4 | **Slack recipe**: chat.postMessage ⇒ `chat.getPermalink` / `conversations.history`; create channel ⇒ `conversations.info` | DO Slack pairs | live test |
| P1.2.5 | **HubSpot recipe**: create/update contact/deal/company ⇒ `objects.get` field compare | DO HubSpot pairs | live test |
| P1.2.6 | Pass-through auth: SDK reuses the caller's client/token for read-back; nothing leaves the process | 03 §5 | no network to cloud in tests |
| P1.2.7 | `unverified` outcome: read-back contradicts result ⇒ level `unverified`, loud log, ledger flag | DeerFlow UNVERIFIED discipline | mismatch test |
| P1.2.8 | **LangGraph adapter**: `attest.langgraph.wrap(graph)` wraps every tool node; sync mode first | — | example agent |
| P1.2.9 | **Demo 2 (M1)**: LangGraph agent sends Gmail + updates HubSpot ⇒ two `verified` entries with evidence ids | — | recorded run + screenshots |

Exit P1.2 (**M1**): first real verified actions end to end, local only.

### P1.3 (week 3) — Gate channels, async modes, OpenAI adapter, MCP proxy

| ID | Task | Source | Done when |
| --- | --- | --- | --- |
| P1.3.1 | Gate abstraction: `ConfirmRequest{action_id, descriptor, reasons, channel, status, resume_token}`; modes sync-block / async-interrupt / pending | 03 §6 | unit tests |
| P1.3.2 | **Slack app** (Bolt): interactive card approve / reject / edit-params; identity of approver recorded | DeerFlow IM channel pattern | live approve in test workspace |
| P1.3.3 | Minimal **web confirm inbox** (served by SDK locally, later cloud) | — | approve from browser |
| P1.3.4 | Async interrupt: LangGraph `interrupt()` integration; resume with token | — | agent pauses and resumes |
| P1.3.5 | **OpenAI Agents SDK adapter** (`function_tool` wrapper + HITL hook) | — | example |
| P1.3.6 | **MCP proxy** (`attest-mcp --upstream …`): intercept `tools/call`, normalize by tool name, decide/gate/verify (MCP tool-pair read-back), return `pending_confirmation` + `attest_resume` tool | DeerFlow MCP client | works with a Gmail MCP server + Claude Code |
| P1.3.7 | Webhook confirm (`POST /confirm`) for custom UIs | — | curl test |

Exit P1.3: every entry point except HTTP gateway works; approvals from Slack.

### P1.4 (week 4) — Cloud v0, dashboard, docs, launch prep → **M2**

| ID | Task | Source | Done when |
| --- | --- | --- | --- |
| P1.4.1 | Cloud API (FastAPI + Postgres): orgs/users/agents/API keys; `POST /v1/attest` (ledger sink), `GET /v1/ledger`, `POST /v1/decide` (policy sync), confirm endpoints | DO Better Auth orgs, schema | deployed (Docker Compose) |
| P1.4.2 | Multi-tenant scoping on every query; hash chain per org; export JSON/CSV | 04 data model | tests |
| P1.4.3 | Dashboard (Next.js): ledger table + drill-down (decision trail, verification evidence), confirm inbox, agents/keys | — | usable |
| P1.4.4 | SDK ⇄ cloud: ledger sink, policy sync, Slack confirms routed via cloud | — | end-to-end with cloud on |
| P1.4.5 | Docs site + **5-minute quickstart**; README; examples (decorator, LangGraph, OpenAI, MCP, unknown app) | — | a stranger can run it |
| P1.4.6 | Test gate: policy, verify (match / mismatch / unverified), ledger integrity, adapters — CI green | 06 principles | CI |
| P1.4.7 | Launch kit: Show HN draft, LangChain integration PR draft, "Why 200 OK is not proof" post, "EU AI Act-compliant agent in 10 min" post | 05 GTM | drafts ready |
| P1.4.8 | **OSS launch (M2)** — MIT, GitHub public, HN, dev social | Founder | live |

Exit P1 (**M2**): OSS live; cloud v0 usable; 3 deep recipes; 4 entry points; docs; launch done.

---

## P2 — Depth + reach (weeks 5–8) → M3, M4

Goal: paid cloud, more recipes, more adapters, marketplaces, public launch.

| ID | Component | Tasks |
| --- | --- | --- |
| P2.1 | Recipes | Google Calendar, Drive/Docs/Sheets, Notion, Linear, Microsoft 365 (Outlook/Teams); **OpenAPI driver** (spec ⇒ read path); **MCP tool-pair detection** |
| P2.2 | Policies | Policies UI (YAML editor + validation), versioning, approver groups, per-agent overrides, retention settings |
| P2.3 | Evidence | IETF agent-audit-trail export; **EU AI Act event-log pack**; signed export manifests; ledger checkpoints |
| P2.4 | Billing | Stripe: Team $99 / Pro $499 / usage per verified action; plan gates; invoices |
| P2.5 | Adapters | Claude Agent SDK, CrewAI, **DeerFlow** (middleware), Vercel AI SDK (via HTTP API until TS SDK) |
| P2.6 | Distribution | Slack Marketplace listing (confirm-gate app); `verified-actions` skill on skills marketplaces; public MCP `verify` server; LangChain integrations page |
| P2.7 | Launch | Public launch: Show HN, content series (3 posts), partner outreach (LangChain, Arcade, Nango) |
| P2.8 | Ops | Error tracking, uptime, backups, rate limits; SDK telemetry opt-in |

Milestones: **M3** first paying team; **M4** public launch. Exit: ≥ 5 paying teams, 8+ deep recipes, 6 adapters, marketplaces live.

---

## P3 — Scale (weeks 9–12)

| ID | Component | Tasks |
| --- | --- | --- |
| P3.1 | HTTP gateway | Outbound REST proxy (`ATTEST_GATEWAY` base URL); URL-pattern recipes; works with Nango / Composio / Arcade / direct callers; single binary with MCP proxy |
| P3.2 | TypeScript SDK | decorator/wrapper, Vercel AI SDK, Mastra, LangChain.js adapters; shared recipe registry (JSON) |
| P3.3 | Cloud auth (optional) | Nango self-hosted for read-only verification credentials when the agent holds no token (API-only / no-code users) |
| P3.4 | Recipe automation | LLM-assisted recipe generation (DeerFlow internal tool): read docs / MCP tool lists ⇒ propose pairs ⇒ human review ⇒ registry; **open recipe registry** (community, versioned) |
| P3.5 | Hardening | signed checkpoints + external anchoring option, SSO (SAML/OIDC), on-prem ledger image, SOC 2 readiness checklist |
| P3.6 | Product | Teams/email confirm channels, agent-activity digests, anomaly flags (unusual verb/target patterns) |

Exit: any language covered; recipe long tail growing automatically; enterprise-readiness path visible.

---

## P4 — Growth (month 4+)

- Partnerships productized: "authorize with Arcade, verify with Attest"; LangChain / Nango co-marketing.
- Vertical packs: business-app agents (done) → finance/payments (very-high-risk policies, dual approval) → DevOps/IT.
- Compliance packs as SKUs (EU AI Act, SOC 2 evidence, ISO 42001).
- Ecosystem: recipe registry contributions, adapter contributions, "Attest-verified" badge for agent products.
- Target **M5**: $10k MRR; seed / partnership conversations from a position of traction.

---

## Dependencies & risks per phase

| Phase | Depends on | Main risk | Mitigation |
| --- | --- | --- | --- |
| P1.1 | P0.5 extraction notes | over-designing the descriptor | ship minimal fields; extend via `extra` |
| P1.2 | test Gmail/Slack/HubSpot accounts (P0.4) | vendor API quirks in read-back | field-level match reports; tolerate eventual consistency with retry window |
| P1.3 | Slack app registration (founder) | framework pause semantics differ | three explicit modes; test each adapter with a pause |
| P1.4 | domain, hosting (founder) | launch before quality | test gate is a hard exit criterion |
| P2 | M2 traction | monetizing too early | free tier generous; charge for ledger retention/confirm/exports |
| P3 | P2 recipes | gateway scope creep | proxy only; no execution features |

---

## Founder checklist by phase

| Phase | Founder must do |
| --- | --- |
| P0 | git DO + ATTEST, decisions, org/domain, test accounts |
| P1 | 15-min DO walkthroughs (policy, actions, connectors), Slack app registration, review demos, run the launch |
| P2 | first 20 developer conversations, Stripe account, marketplace accounts, partner intros |
| P3 | enterprise-readiness conversations, SOC 2 vendor choice |
| P4 | partnerships, hiring (first DevRel / support), fundraising if chosen |
