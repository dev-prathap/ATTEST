# Attest — Proof layer for AI agents

> **Decide → Gate → Verify → Attest.**
> When an AI agent takes an action in the real world, Attest decides whether it may, gates it behind a human when it matters, verifies from the system of record that it actually happened, and records tamper-evident evidence.

Attest is **not** an agent framework, not a connector platform, not a guardrail filter. It is the layer that lets a team say, with proof: *"this agent did exactly this, as this person, and it worked."*

## Read in this order

| Doc | What it locks |
| --- | --- |
| [01 — Vision](./docs/01-vision.md) | What Attest is, what it is not, the thesis |
| [02 — Product](./docs/02-product.md) | The four steps, surfaces, what a customer experiences |
| [03 — Universal adapter](./docs/03-universal-adapter.md) | **All apps, all actions**: descriptor, entry points, verification ladder, auth, confirm, policy |
| [04 — Architecture](./docs/04-architecture.md) | SDK + Cloud, stack, data model, ledger |
| [05 — Market & positioning](./docs/05-market-positioning.md) | Why now, competitors, first vertical, go-to-market |
| [06 — Build plan](./docs/06-build-plan.md) | Phases, weekly plan, what we reuse, what we do not build |
| [07 — Decisions](./docs/07-decisions.md) | Locked decisions and open questions |
| [08 — Phase plan](./docs/08-phase-plan.md) | Detailed phase-wise split: task IDs, deliverables, exit criteria, milestones, founder checklist |

## Code
- [attest/](./attest/) — the Python SDK (P1.1–P1.3 done: core, read-back, gates, adapters, MCP proxy). Quickstart in [attest/README.md](./attest/README.md).
- [examples/unknown_app.py](./examples/unknown_app.py) — an app Attest has never seen, L1 → L2 → L3.
- [examples/langgraph_agent.py](./examples/langgraph_agent.py) — LangGraph agent, Gmail + HubSpot, two `verified` entries.
- [docs/notes/do-extraction.md](./docs/notes/do-extraction.md) — what was lifted from DO / DeerFlow and how.

## One-line rules
- We never execute the customer's action. Their tool executes; we observe, decide, gate, verify, record.
- Coverage is universal (any app, any action, any framework, any language). Verification depth is layered and honest.
- Open-source SDK (MIT). Paid cloud (ledger, confirm inbox, policies, exports).
- Developer-led, self-serve, USD. No enterprise sales motion in year one.

## Lineage
Attest is extracted from two working codebases: **DO** (policy engine, read-back verification pairs, evidence ledger, Nango auth) and **DeerFlow** (tool receipts, verification patterns, MCP/IM channel adapters). Nothing here is theoretical — every core mechanism already runs against real Gmail, Slack, HubSpot, Notion, Linear and Google Workspace.
