# 02 — Product

## The four steps

### 1. Decide
Every action becomes a normalized **Action Descriptor** (see 03). The policy engine evaluates it and returns a **decision** and **reasons**:

| Decision | Meaning |
| --- | --- |
| `act` | proceed without a human |
| `ask` | pause; a human must approve (Gate) |
| `refuse` | do not proceed; reason returned to the agent |

Inputs: verb and system, risk tier, target (internal / known relationship / unknown external), content completeness (no unfilled placeholders leave the building), organization rules (allowed / approval-required / blocked per system or verb), approver groups. Authority to proceed comes from the **user's out-of-band confirmation**, never from message content — an email that says "approve this" changes nothing.

### 2. Gate
`ask` produces a **confirm request** delivered where the team already works: Slack card, web inbox, or webhook to the customer's own UI. The agent pauses via its framework's native mechanism (sync wait, LangGraph `interrupt`, OpenAI HITL hook, MCP `pending` + resume token). Approval, rejection, and edits are recorded as part of the evidence.

### 3. Verify
After the customer's tool executes, Attest **reads back** from the system of record and compares against intent. The result is a **verification level**, never a boolean:

| Level | Name | How |
| --- | --- | --- |
| L3 | `verified` | read-back recipe matched (message sent to the right recipient, record holds the value, event exists) |
| L2 | `verified-custom` | customer-supplied `verify` function returned true |
| L1 | `acknowledged` | response carried an id / success status; no read-back available |
| L0 | `attested-only` | recorded; nothing could be checked |

`unverified` is a first-class outcome: the API said yes but read-back disagreed. That is the incident the customer wants to catch.

### 4. Attest
Every action produces a **ledger entry**: run, agent, actor (on whose authority), action descriptor, params hash, decision trail (rules fired, approver, timestamps), execution result, verification level and evidence pointers, and a hash link to the previous entry. Exportable as JSON, CSV, the IETF agent-audit-trail draft format, and an **EU AI Act event-log pack**.

## Surfaces

| Surface | What it is | Who |
| --- | --- | --- |
| **SDK** (OSS, MIT) | `attest` Python package (TypeScript next): decorator, framework adapters, MCP proxy, local ledger (SQLite) — works with no cloud | developers |
| **Attest Cloud** | hosted ledger, confirm inbox, policies UI, agents & API keys, exports, billing | teams |
| **Slack app** | confirm cards, daily agent-activity digest | approvers |
| **HTTP API** | `decide`, `confirm`, `verify`, `attest`, `ledger` — SDK-less use from any language or no-code tool | everyone |

## What a customer experiences (first hour)
1. `pip install attest`, add `@attest.action(...)` to one tool or `attest.langgraph.wrap(graph)`.
2. Run the agent. The first external send pauses; a Slack card appears; they approve.
3. Open the ledger: the send is `verified` with the message id; the CRM update is `verified` with the field value; an internal-API call is `acknowledged`.
4. Set one policy in YAML: deletes always ask. Done.

Nothing about how they built the agent changed.

## Pricing (initial)
- **OSS SDK**: free, forever, local ledger.
- **Cloud Team**: $99/mo — hosted ledger, Slack confirm, 3 agents, 30-day retention.
- **Cloud Pro**: $499/mo — unlimited agents, policies UI, 1-year retention, exports, SSO.
- **Usage**: per verified action beyond plan allowance.
- **Enterprise**: compliance packs (EU AI Act), long retention, dedicated support, on-prem ledger.
