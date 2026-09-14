---
name: verified-actions
description: Make an AI agent's real-world actions accountable with Attest — decide by policy, gate risky actions behind a human, verify by reading back from the system of record, and record a hash-chained ledger entry. Use when adding email/CRM/ticket/document/payment tools to an agent, when asked "did the agent actually do it", when a team needs an audit trail or EU AI Act-style event log for agent actions, or when wiring an MCP server that performs writes.
---

# Verified actions with Attest

Attest never executes the action — the agent's own tool does. Attest decides, gates, verifies, and records.

## Pick the entry point

| you have | do this |
| --- | --- |
| a Python function that acts | `@attest.action(system=…, verb=…, target=…)` on it |
| LangGraph / LangChain tools | `attest.adapters.langgraph.wrap_tools(tools, at, mapping=…)` or `AttestMiddleware` |
| OpenAI Agents SDK | `attest.adapters.openai_agents.wrap_tools(tools, at, mapping=…)` |
| Claude Agent SDK | `pre, post = attest.adapters.claude_agent_sdk.hooks(at, mapping=…)` as PreToolUse / PostToolUse |
| CrewAI | `attest.adapters.crewai.wrap_tools(tools, at, mapping=…)` |
| an MCP server that writes | run it behind `attest-mcp --upstream "<cmd>" --server <name>` (zero code) |
| no SDK at all | call the `attest_decide` / `attest_confirm` / `attest_record` / `attest_verify` tools on `attest-mcp-server` |

`mapping` gives each tool its `system`, `verb`, and which argument is the `target`; unmapped tools are inferred
from their names (`gmail_send_message` ⇒ gmail / send).

## Get to `verified`

Give Attest the credential the agent already holds; it reads back in-process:

```python
at = Attest(readers={"gmail": gmail_service, "hubspot": hubspot_token}, http_get=session_get)
```

Levels: `verified` (record matched intent) · `verified-custom` (your `verify=`) · `acknowledged` (API said yes,
nothing read back) · `attested-only` · `unverified` (**contradiction** — surface it). Never call an
`acknowledged` action "done" in a report; say what level the ledger holds.

## Policy and approvals

`attest.yaml` — first match wins; external sends, deletes, payments and unknown writes ask by default.
Approvers: console, `attest serve` inbox, Slack card, webhook, or the framework's own pause (LangGraph
`interrupt`, MCP pending + `attest_resume`). Use `groups:` for approver groups, `agents:` for per-agent rules.

## Evidence

`attest ledger` · `attest verify` (hash chain) · `attest export --format ietf|eu-ai-act` · `attest checkpoint`.
With Attest Cloud (`Attest.cloud(url, key)`): shared ledger, dashboard inbox, signed exports.

## When reporting to the user

Cite the ledger row: `#seq system.verb → target — level`. If a level is `unverified`, say so first.
