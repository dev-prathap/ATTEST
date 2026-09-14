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
| P0.1 | DO repo: `git init`, `.gitignore` (.env, .fernet_key, .oauth_pkce.json, _ref-*, node_modules, .venv), commit, push to private GitHub | Claude | **Done 2026-09-12** — `dev-pratapk/DO`, commit `df85d52`, 1,642 files, secrets and `_ref-*` excluded |
| P0.2 | ATTEST repo: first commit, private remote | Claude | **Done 2026-09-12** — `dev-pratapk/ATTEST` |
| P0.3 | Confirm locked decisions (07): name, wrapper model, Python-first, Gmail/Slack/HubSpot first | Founder | 07 updated |
| P0.4 | GitHub org, domain, test Slack workspace, test Gmail/HubSpot accounts | Founder | credentials in a local `.env` |
| P0.5 | Claude: read DO `app/brain/execution/policy.py`, `app/brain/execution/actions.py` (ref resolver), `app/brain/connectors/providers/template.py` (VERIFY_WITH, `_auto_pair`, verb classifier), `app/brain/connectors/providers/google.py` (`verify()`), `connectors/registry.py`, `connectors/capabilities.py`, `schema.sql`; DeerFlow receipt middleware; write extraction notes | Claude | **Done 2026-09-12** — [notes/do-extraction.md](./notes/do-extraction.md) |

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
| P1.1.2 | Verb taxonomy + detection: MCP tool-name patterns, REST URL patterns, SDK call names, heuristics; unknown ⇒ `write` (DO defaults unknown to `update` — change it) | DO `template.py` `VERB_MAP`, `_verb`, `_risk`, `RISK_BY_VERB`, `VERB_OVERRIDES`/`RISK_OVERRIDES`; `capabilities.py` `WRITE_VERBS`; `registry.py` `SYSTEM_LABELS`. DO tokenises hyphenated names only — add snake_case, dotted SDK paths, and `METHOD + URL` | ≥ 40 pattern tests incl. unknown app |
| P1.1.3 | Policy engine: YAML rules (`match` on descriptor fields, `decision`, `approvers`) + built-in R0–R4 (org rule, acting-on-other's-connection, recipient legitimacy internal/known/unknown, placeholder hold, risk-tier ⇒ confirm). R2 sets `target_class` on the descriptor; the unknown-external send outcome comes from YAML (default `ask`), not hard-coded Refuse as in DO. Collapse DO's `Act + requires_confirm` and `Ask` into `ask`, keeping the hold reason | DO `policy.py` with three injected callables (`org_rule`, `org_domain`, `is_known_domain`) | `PolicyResult{decision, risk_tier, reasons, target_class}`; tests for every rule |
| P1.1.4 | Local ledger: SQLite, append-only, `prev_hash`/`hash` chain, `verify_chain()`. New code — DO's `ledger_event` has no chain | row shape from DO `action_run`; `params_hash`/`result_hash` from DeerFlow `make_tool_receipt` (sorted-key JSON ⇒ sha256) | tamper test (edit a row ⇒ chain breaks) |
| P1.1.5 | `@attest.action(system=, verb=, risk=, verify=)` decorator + `Attest()` client; sync + async | — | decorated function runs decide → (console gate) → execute → verify → ledger |
| P1.1.6 | Verification ladder L0/L1: `attested-only`, `acknowledged` (result has id/status); `verify=` custom ⇒ L2 | 03 §4 | levels recorded |
| P1.1.7 | Console gate (y/n) for local use | — | works without cloud |
| P1.1.8 | **Demo 1 — unknown app**: `POST api.someweirdcrm.io/v2/leads` through the decorator ⇒ recorded, verb `create`, policy applied, L1 | 03 §4 walkthrough | script in `examples/` |

Exit P1.1: `pip install -e .`; any function can be attested; ledger chain verifies; unknown app works.

**Status 2026-09-12: P1.1 done.** `attest/` package (descriptor · registry with MCP / URL / SDK / function-name detection · policy R0–R4 + YAML · hash-chained SQLite ledger · L0/L1/L2 ladder with read-back driver interface · console + auto gate · `@action` sync/async · API-only `attest()`), 176 tests, `examples/unknown_app.py`, CI on 3.11–3.13. See [attest/README.md](../attest/README.md).

### P1.2 (week 2) — Read-back verification + LangGraph → **M1**

| ID | Task | Source | Done when |
| --- | --- | --- | --- |
| P1.2.1 | Read-back driver interface: `ReadBack(system, verb) -> (fetch(result, params), compare(intent, fetched) -> MatchReport)`. Must distinguish existence-only recipes (DO's 65 pairs) from field-comparing ones (DO's Google `verify()`); existence-only is not silently `verified` | DO `template.py` `VERIFY_WITH` + `actions.py` `_ref`/`_dig`/`_verify_with`; `google.py` `verify()` | interface + fake driver tests |
| P1.2.2 | **Convention driver**: create/update-X ⇒ get-X using returned id (REST + SDK) | DO `template.py` `_auto_pair` (lift verbatim; generalise to `POST /x` ⇒ `GET /x/{id}`) | works on the unknown-app demo ⇒ L3 |
| P1.2.3 | **Gmail recipe**: send/reply ⇒ `messages.get` (SENT label, first recipient ⊂ To, reply threadId); draft ⇒ `drafts.get`; label/archive ⇒ label set check | DO `google.py` `GoogleConnector.verify()` — imperative, field-comparing; port as a `Recipe` with comparators | live test with test account |
| P1.2.4 | **Slack recipe**: chat.postMessage ⇒ `conversations.history(channel, latest=ts, inclusive, limit=1)` with text/channel compare; create channel ⇒ `conversations.info` | DO has 2 existence-only pairs that run through the Nango proxy — direct-SDK read-back and field compare are **new** | live test |
| P1.2.5 | **HubSpot recipe**: create/update contact/deal/company ⇒ `objects.<type>.basic_api.get_by_id(properties=…)` field compare | DO has 3 create-only existence pairs via Nango. **Update read-back and field compare are new**; the convention driver can derive update ⇒ get | live test |
| P1.2.6 | Pass-through auth: SDK reuses the caller's client/token for read-back; nothing leaves the process | 03 §5 | no network to cloud in tests |
| P1.2.7 | `unverified` outcome: read-back **contradicts** result ⇒ level `unverified`, loud log, ledger flag. Fetch error or unresolvable ref ⇒ `acknowledged` with error evidence, never `unverified` (DO conflates these) | DO `actions.py` "read-back verification did not confirm it" summary; DeerFlow `render_citation_verdict` UNVERIFIED vocabulary | mismatch test + fetch-error test |
| P1.2.8 | **LangGraph adapter**: `attest.langgraph.wrap(graph)` wraps every tool node; sync mode first. Must be the outermost tool-call layer so short-circuiting middlewares cannot gap the ledger | DeerFlow `ToolReceiptMiddleware.wrap_tool_call` / `awrap_tool_call` pattern | example agent |
| P1.2.9 | **Demo 2 (M1)**: LangGraph agent sends Gmail + updates HubSpot ⇒ two `verified` entries with evidence ids | — | recorded run + screenshots |

Exit P1.2 (**M1**): first real verified actions end to end, local only.

**Status 2026-09-15: P1.2 code done; M1 pending live credentials.** Read-back driver interface with `MatchReport`; convention driver (REST `GET <url>/<id>` + `lookup=` for SDKs); reviewed recipes for Gmail (send/reply/draft/labels, ported from DO `google.py`), Slack (send, create channel) and HubSpot (any object, create/update) with field-level compare; pass-through readers (vendor client object, bearer token, or any `fetch` callable — nothing leaves the process); `unverified` on contradiction, degrade on fetch error; LangGraph adapter (`wrap_tools`, `wrap(graph)`, `AttestMiddleware`). 230 tests against client-shaped fakes. `examples/langgraph_agent.py` (Demo 2) yields two `verified` entries with fakes and switches to real Gmail/HubSpot when `ATTEST_LIVE_*` tokens are set. `tests/live/` holds the real-account tests (skipped without tokens) — **M1 is claimed only after those pass** (needs P0.4 accounts).

### P1.3 (week 3) — Gate channels, async modes, OpenAI adapter, MCP proxy

| ID | Task | Source | Done when |
| --- | --- | --- | --- |
| P1.3.1 | Gate abstraction: `ConfirmRequest{action_id, descriptor, reasons, channel, status, resume_token}`; modes sync-block / async-interrupt / pending | 03 §6 | unit tests |
| P1.3.2 | **Slack app** (Bolt): interactive card approve / reject / edit-params; identity of approver recorded | new code (DeerFlow's IM channels are app-specific, nothing reusable) | live approve in test workspace |
| P1.3.3 | Minimal **web confirm inbox** (served by SDK locally, later cloud) | — | approve from browser |
| P1.3.4 | Async interrupt: LangGraph `interrupt()` integration; resume with token | — | agent pauses and resumes |
| P1.3.5 | **OpenAI Agents SDK adapter** (`function_tool` wrapper + HITL hook) | — | example |
| P1.3.6 | **MCP proxy** (`attest-mcp --upstream …`): intercept `tools/call`, normalize by tool name, decide/gate/verify (MCP tool-pair read-back), return `pending_confirmation` + `attest_resume` tool | new code (DEER has an MCP *client*, not a proxy) | works with a Gmail MCP server + Claude Code |
| P1.3.7 | Webhook confirm (`POST /confirm`) for custom UIs | — | curl test |

Exit P1.3: every entry point except HTTP gateway works; approvals from Slack.

**Status 2026-09-15: P1.3 code done; live Slack approval pending app registration (P0.4).** `PendingStore` (SQLite, shared with the ledger) + `StoreGate` (block / pending) with notifiers: `SlackNotifier` (Block Kit card, approve/reject buttons, approver identity, card updated with outcome; `handle_interaction` + signature check, optional `bolt_app`), `WebhookNotifier` (signed POST). `InterruptGate` for LangGraph `interrupt()` / `Command(resume=…)`, replay-safe. `Attest.resume()` / `aresume()` with edits, same-process or `execute=` cross-process; ledger rows link via `resumed_from`. Web inbox + API (`attest serve`, stdlib), `attest` CLI (ledger / verify / pending / confirm / export). OpenAI Agents SDK adapter (`FunctionTool` wrap, pending ⇒ resume token). **MCP stdio proxy** `attest-mcp` (tools/call interception, `attest_resume` tool, MCP tool-pair read-back ⇒ L3, block / pending / auto), tested against a fake MCP server as a subprocess. 273 tests. Not yet: HTTP-transport MCP upstreams (stdio only), Slack modal for edits (edits go through the inbox).

### P1.4 (week 4) — Cloud v0, dashboard, docs, launch prep → **M2**

| ID | Task | Source | Done when |
| --- | --- | --- | --- |
| P1.4.1 | Cloud API (FastAPI + Postgres): orgs/users/agents/API keys; `POST /v1/attest` (ledger sink), `GET /v1/ledger`, `POST /v1/decide` (policy sync), confirm endpoints. Sink must store `params_hash` + allow-listed preview — DO's `ActionOutcome.to_dict()` exposes full params | DO `schema.sql` `action_run`, `permission`; Better Auth lives in DO `app/web` (unreviewed; auth provider still open in 07) | deployed (Docker Compose) |
| P1.4.2 | Multi-tenant scoping on every query; hash chain per org; export JSON/CSV | 04 data model | tests |
| P1.4.3 | Dashboard (Next.js): ledger table + drill-down (decision trail, verification evidence), confirm inbox, agents/keys | — | usable |
| P1.4.4 | SDK ⇄ cloud: ledger sink, policy sync, Slack confirms routed via cloud | — | end-to-end with cloud on |
| P1.4.5 | Docs site + **5-minute quickstart**; README; examples (decorator, LangGraph, OpenAI, MCP, unknown app) | — | a stranger can run it |
| P1.4.6 | Test gate: policy, verify (match / mismatch / unverified), ledger integrity, adapters — CI green | 06 principles | CI |
| P1.4.7 | Launch kit: Show HN draft, LangChain integration PR draft, "Why 200 OK is not proof" post, "EU AI Act-compliant agent in 10 min" post | 05 GTM | drafts ready |
| P1.4.8 | **OSS launch (M2)** — MIT, GitHub public, HN, dev social | Founder | live |

Exit P1 (**M2**): OSS live; cloud v0 usable; 3 deep recipes; 4 entry points; docs; launch done.

**Status 2026-09-15: P1.4.1–P1.4.7 done; P1.4.8 (launch) is the founder's.**
- P1.4.1/2 `cloud/` — FastAPI + SQLAlchemy (Postgres via `DATABASE_URL`, SQLite for tests): orgs, API keys with roles (agent / approver / admin), agents (auto-registered on sink), versioned policy (`GET/PUT /v1/policy`, `POST /v1/decide`), ledger sink (`POST /v1/attest`, rejects raw params, idempotent, **per-org hash chain** with the SDK's chain code), queries / verify / stats / export with signed manifest, confirm create / list / decide with Slack + webhook notifiers from org settings, `POST /slack/interact`. Every query scoped by the key's org. 21 tests incl. isolation and tamper detection.
- P1.4.3 `dashboard/` — Next.js 15 (app router, no Tailwind in v0): ledger table + drill-down drawer (decision trail, confirm record, params preview, execution, verification evidence, hash), confirm inbox (approve / reject / edit, recent decisions), settings (connection, policy editor with versions, agents, API keys, org channels). Builds clean; talks to the cloud with an API key.
- P1.4.4 `attest/cloud.py` — `Attest.cloud(url, api_key)`: `CloudLedger` (local chain + push, outbox retry when the cloud is down), `cloud_policy` / `refresh_policy`, `CloudStore` so `StoreGate` and `resume()` work over the cloud; Slack confirms routed via the cloud's org settings. End-to-end tests through the ASGI app.
- P1.4.5 `docs/site` (mkdocs-material, strict build) — quickstart, concepts, levels, policy, five entry points, gates, recipes, ledger, cloud, CLI. Examples: decorator (unknown app), LangGraph, OpenAI Agents, MCP config, API-only, cloud.
- P1.4.6 CI: sdk (3.11–3.13: ruff, SDK + cloud tests, all examples), docs (strict), dashboard (build).
- P1.4.7 `launch/` — Show HN, "Why 200 OK is not proof", "EU AI Act-ready event log in 10 minutes" (hedged, not legal advice), LangChain integrations PR draft.
- `deploy/` — Dockerfiles + compose (Postgres 16, API :8400, dashboard :3400).
- **Open (doc 07):** cloud auth provider. v0 uses API keys with roles and no user login; the dashboard authenticates with a key. Better Auth / WorkOS / Clerk decision still pending. Stripe, retention, SSO are P2.

---

## P2 — Depth + reach (weeks 5–8) → M3, M4

Goal: paid cloud, more recipes, more adapters, marketplaces, public launch.

| ID | Component | Tasks |
| --- | --- | --- |
| P2.1 | Recipes | Google Calendar, Drive/Docs/Sheets, Notion, Linear, Microsoft 365 (Outlook/Teams); **OpenAPI driver** (spec ⇒ read path); **MCP tool-pair detection** — **done 2026-09-15**: 19 recipes (12 new: calendar event, drive file/share, docs, sheets values, notion page/database, linear issue/project/comment, outlook send (sentitems search) / event, teams message), readers for each with client / token / fetch pass-through, `OpenApiDriver` (nested paths, no-guess fallback); MCP pairs since P1.3. Live tests still need P0.4 accounts. |
| P2.2 | Policies | Policies UI (YAML editor + validation), versioning, approver groups, per-agent overrides, retention settings — **done 2026-09-15**: `groups:` resolve onto the confirm request (`approver_members`), the cloud refuses a decision from someone outside the group (admins exempt), `agents:` overrides evaluate before global rules, `retention_days` org setting + `POST /v1/ledger/prune` (local: `attest prune`). |
| P2.3 | Evidence | IETF agent-audit-trail export; **EU AI Act event-log pack**; signed export manifests; ledger checkpoints — **done 2026-09-15**: `export --format ietf` (JSONL records per draft-sharif-agent-audit-trail: record_id, timestamp, agent_id, session_id, action_type, action_detail, outcome, trust_level L0–L3, parent_record_id, prev_hash, record_phase, human_override, input/output hashes, deny_reasons), `export --format eu-ai-act` (system, period, events with human-oversight + verification, integrity with checkpoints, field map, signed manifest; hedged as engineering aid), HMAC-signed checkpoints (`attest checkpoint`, `POST /v1/ledger/checkpoint`, `ATTEST_LEDGER_KEY` / `ATTEST_SIGNING_KEY`); pruned ledgers verify from the checkpoint anchor. Ed25519 / external anchoring stays P3. |
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
| P1.1 | P0.5 extraction notes (done — [notes/do-extraction.md](./notes/do-extraction.md) §8 lists the exact line ranges to copy) | over-designing the descriptor | ship minimal fields; extend via `extra` |
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
