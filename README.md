# Attest — Proof layer for AI agents

[![ci](https://github.com/dev-prathap/ATTEST/actions/workflows/ci.yml/badge.svg)](https://github.com/dev-prathap/ATTEST/actions/workflows/ci.yml) [![npm](https://img.shields.io/npm/v/attestlayer?label=npm%20attestlayer)](https://www.npmjs.com/package/attestlayer) [![docs](https://img.shields.io/badge/docs-dev--prathap.github.io%2FATTEST-black)](https://dev-prathap.github.io/ATTEST/) [![license](https://img.shields.io/badge/license-MIT-green)](./LICENSE)

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

## Quickstart

Brand **Attest** · PyPI `attestlayer` · npm `attestlayer` · deploy runbook in [DEPLOY.md](./DEPLOY.md).

```bash
pip install attestlayer              # brand: Attest · import attest · CLI attest
```

```python
import attest

@attest.action(system="gmail", verb="send", target="to")
def send_email(to, subject, body): ...
```

The first external send pauses for a human; the ledger row says `acknowledged`, or `verified` once Attest can
read back with the agent's own credentials (`Attest(readers={"gmail": service})`). `attest ledger` · `attest verify`.
Full docs: `mkdocs serve` → [docs/site](./docs/site/quickstart.md).

## Repository

| path | what |
| --- | --- |
| [attest/](./attest/) | Python SDK — descriptor, registry, policy, hash-chained ledger, verification ladder + recipes, gates (console / Slack / webhook / inbox / LangGraph interrupt / pending + resume), adapters (LangGraph, OpenAI Agents), MCP proxy, CLI, cloud client. [attest/README.md](./attest/README.md) |
| [cloud/](./cloud/) | Attest Cloud v0 — FastAPI + Postgres: orgs, keys, agents, versioned policy, per-org hash-chained ledger, confirm inbox with Slack / webhook, exports |
| [dashboard/](./dashboard/) | Next.js dashboard — ledger drill-down, confirm inbox, policy / keys / settings |
| [examples/](./examples/) | unknown app (L1 → L3), LangGraph agent (two `verified` rows), OpenAI Agents, MCP config, API-only, cloud |
| [docs/site/](./docs/site/) | documentation site (mkdocs) · [docs/](./docs/) — product docs 01–08 · [docs/notes](./docs/notes/do-extraction.md) — DO / DeerFlow extraction |
| [deploy/](./deploy/) | Dockerfiles + compose (Postgres, API :8400, dashboard :3400) |
| [launch/](./launch/) | Show HN, blog drafts, LangChain integration PR draft |
| [DEPLOY.md](./DEPLOY.md) · [CHANGELOG.md](./CHANGELOG.md) | release (`git tag vX.Y.Z` → PyPI, npm, GHCR, Pages) and hosting runbook |

```bash
pytest -q && (cd cloud && pytest -q)                   # 273 + 21 tests
ATTEST_AUTO_APPROVE=1 python examples/langgraph_agent.py
cd deploy && cp .env.example .env && docker compose up  # cloud + dashboard
```

## One-line rules
- We never execute the customer's action. Their tool executes; we observe, decide, gate, verify, record.
- Coverage is universal (any app, any action, any framework, any language). Verification depth is layered and honest.
- Open-source SDK (MIT). Paid cloud (ledger, confirm inbox, policies, exports).
- Developer-led, self-serve, USD. No enterprise sales motion in year one.

## Install from registries

| where | how |
| --- | --- |
| PyPI *(publishing pending)* | `pip install attestlayer` → `attest`, `attest-mcp`, `attest-mcp-server`, `attest-gateway`, `attestlayer` |
| MCP Registry | `io.github.dev-prathap/attest` (verify server) · `io.github.dev-prathap/attest-proxy` (zero-code proxy) — `uvx attestlayer` |
| Claude Desktop / Smithery | MCPB bundle from `mcp/mcpb` (`mcpb pack mcp/mcpb`) |
| npm | `npm install attestlayer` — **live** |
| Docker | `ghcr.io/dev-prathap/attest-api`, `ghcr.io/dev-prathap/attest-dashboard` |

<!-- mcp-name: io.github.dev-prathap/attest -->
<!-- mcp-name: io.github.dev-prathap/attest-proxy -->

## Lineage
Attest is extracted from two working codebases: **DO** (policy engine, read-back verification pairs, evidence ledger, Nango auth) and **DeerFlow** (tool receipts, verification patterns, MCP/IM channel adapters). Nothing here is theoretical — every core mechanism already runs against real Gmail, Slack, HubSpot, Notion, Linear and Google Workspace.
