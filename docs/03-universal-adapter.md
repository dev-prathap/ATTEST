# 03 — Universal Adapter: all apps, all actions

**Rule:** we never say "your stack is not supported." Coverage is universal on day one; verification depth is layered and honest.

We achieve this by refusing to integrate with every way an agent can act. Instead: **one contract, several entry points, a recipe registry that grows automatically, and a verification ladder with an L0 floor.**

---

## 1. One contract — the Action Descriptor

Everything entering Attest is normalized to:

```json
{
  "system":  "gmail",                   // app; "unknown" allowed
  "verb":    "send",                    // read|search|create|update|delete|send|share|pay|approve|execute|write
  "target":  "arun@newco.com",          // recipient / record / resource
  "params":  { "subject": "…", "body_hash": "…" },
  "actor":   "ram@acme.com",            // on whose authority
  "agent":   "followup-agent@v3",
  "run_id":  "…",
  "result":  { "id": "18f3…" }          // filled after execution
}
```

Policy, gate, verify and ledger operate **only** on this shape. Supporting a new framework or app means mapping to the descriptor — the core never changes.

---

## 2. Entry points — however they act, one of these fits

| # | Entry point | Fits | Code change |
| --- | --- | --- | --- |
| 1 | **Decorator / wrapper** — `@attest.action(...)` on the customer's own function | custom code, any vendor SDK | one line per tool |
| 2 | **Framework adapter** — LangGraph, OpenAI Agents SDK, Claude Agent SDK, CrewAI, DeerFlow, Vercel AI SDK | framework users; **all tools wrapped automatically** | one line total |
| 3 | **MCP proxy** — Attest between the agent and *any* MCP server (stdio/HTTP) | Claude Code, Cursor, DeerFlow, official Google/HubSpot/Slack MCP servers | **zero** — config only |
| 4 | **HTTP gateway** — outbound REST through an Attest proxy | direct API callers, Nango / Composio / Arcade users, any language | zero — change base URL |
| 5 | **API-only** — `POST /attest` with what happened (+ optional evidence) | n8n, Zapier, Make, legacy, anything else | one HTTP call |

Entry point 5 is the **floor**: anything can at least be recorded.

The same action through three paths normalizes to the same descriptor:

```python
# A — own code
@attest.action(system="gmail", verb="send")
def send_email(to, subject, body): return gmail.send(...)

# B — LangGraph, all tools at once
graph = attest.langgraph.wrap(graph)
```
```json
// C — MCP, zero code
{ "mcpServers": { "gmail": { "command": "attest-mcp", "args": ["--upstream", "gmail-mcp"] } } }
```

---

## 3. Recipe registry — system & verb auto-detection

Customers should not label every action. The registry infers:

- **MCP tool names** → `gmail_send_message` ⇒ `{gmail, send}`; `hubspot_update_deal` ⇒ `{hubspot, update}`
- **REST URL patterns** → `POST gmail.googleapis.com/…/messages/send` ⇒ `{gmail, send}`; `PATCH api.hubapi.com/crm/v3/objects/deals/{id}` ⇒ `{hubspot, update}`
- **SDK call names** → `hubspot.crm.deals.update` ⇒ `{hubspot, update}`
- **Verb heuristics** for unknown systems → method + path/name tokens (`send|post|create|update|delete|pay|share`) ⇒ verb; unmatched write ⇒ `write`

Unknown system ⇒ `system: "unknown"`, verb still classified ⇒ **default policy by verb applies** (delete / pay / external send ⇒ high risk). Customers may override any mapping. (Verb aliasing, system registry and risk-by-verb are lifted from DO.)

---

## 4. Verification ladder

| Level | Name | When |
| --- | --- | --- |
| L3 | `verified` | read-back recipe exists and matched |
| L2 | `verified-custom` | customer `verify=` function |
| L1 | `acknowledged` | result carries id / success; no read-back |
| L0 | `attested-only` | recorded; nothing checkable |
| — | `unverified` | read-back **contradicts** the claimed result — surfaced loudly |

**Every ledger entry carries its level.** Coverage 100 %; depth grows per system.

### How depth scales without hand-writing 1,000 recipes
1. **Convention** — `create/update X` ⇒ `get X` with the returned id (DO already applies this per family).
2. **OpenAPI-driven** — when a spec is available, derive the read path automatically.
3. **MCP tool-pair detection** — a server exposing `create_issue` and `get_issue` yields a pair.
4. **LLM-generated recipes** — read API docs / tool lists, propose verify pairs, human-review, publish to the registry (DeerFlow can be the internal tool for this).
5. **Open recipe registry** — community-contributed, versioned, MIT.

Top ~20 systems are hand-reviewed; the long tail is automatic (L1 / L3-by-convention); everything else is L0.

### Walkthrough — an app we have never seen
`POST https://api.someweirdcrm.io/v2/leads`
1. Descriptor: `system: someweirdcrm`, `verb: create`, target `leads` → **recorded**.
2. Policy by verb: `create` ⇒ medium ⇒ org default (act or ask).
3. Gate if needed — app-agnostic.
4. Customer executes.
5. Verify: response `{id: "L-991"}` ⇒ L1; convention `GET /v2/leads/L-991` ⇒ match ⇒ **L3**; spec present ⇒ exact path; `verify=` ⇒ L2; nothing ⇒ L0.
6. Ledger entry with level.

Every step works for an unknown app. That is "all apps."

---

## 5. Authentication — never block on our OAuth

| Mode | How | Default? |
| --- | --- | --- |
| **Pass-through** | the agent already holds a token; the SDK reuses it for read-back **locally**; tokens never reach the cloud | yes |
| **Custom verify** | customer's own client checks (L2); we never see credentials | yes |
| **Nango (cloud)** | read-only connection in Attest Cloud for server-side verification when the agent has no token (API-only / no-code users) | optional, enterprise |

Modes 1 + 2 cover ~90 % of cases with zero connector work.

---

## 6. Confirm modes — frameworks pause differently

| Mode | Mechanism | Fits |
| --- | --- | --- |
| Sync block | SDK waits (with timeout) for approval | scripts, sync tools |
| Async interrupt | `pending` + `resume_token` → framework interrupt (LangGraph `interrupt()`, OpenAI HITL hooks, DeerFlow `ask_clarification`) | agent frameworks |
| MCP pending | proxy returns `{status: "pending_confirmation", resume: …}`; agent later calls `attest_resume` | MCP stacks |
| Webhook | customer UI approves via `POST /confirm` | custom UIs, n8n |

Channels: Slack, web inbox, webhook; later Teams and email.

---

## 7. Policy — declarative, descriptor-based, per-system code never required

```yaml
policies:
  - match: { verb: [send, share], target: external }   # any system
    decision: ask
  - match: { verb: [delete, pay] }
    decision: ask
    approvers: [finance-leads]
  - match: { system: hubspot, verb: update }
    decision: act
  - match: { system: unknown, verb: write }
    decision: ask
  - match: { target_domain: [competitor.com] }
    decision: refuse
```

Rules evaluate on the descriptor, so new systems inherit sensible behavior by verb and target. Engine rules R0–R4 (org permission, acting on another's connection, recipient legitimacy, content completeness, risk tier ⇒ confirmation) come from DO's `policy.py`.

---

## 8. Languages
1. **Python SDK** first (LangGraph, OpenAI, CrewAI, DeerFlow).
2. **TypeScript SDK** second (Vercel AI SDK, Mastra, LangChain.js).
3. **MCP proxy + HTTP gateway + API are language-agnostic** — Go, Java, Ruby, no-code all covered without an SDK.

## Summary

| Customer approach | Entry | Depth |
| --- | --- | --- |
| Own Python code + SDKs | decorator | L3 / L2 |
| LangGraph / OpenAI / CrewAI / DeerFlow | adapter | L3 / L2 |
| Claude Code / Cursor / MCP servers | MCP proxy | L3 |
| Nango / Composio / Arcade / direct REST | HTTP gateway | L3 / L1 |
| n8n / Zapier / Make / legacy | API-only | L2 / L0 |
| TypeScript / Go / anything | gateway / API | L1 / L0 |

**Coverage 100 %. Depth layered. Nobody is turned away.**
