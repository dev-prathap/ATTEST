# Attest — prove what your AI agent actually did

[![ci](https://github.com/dev-prathap/ATTEST/actions/workflows/ci.yml/badge.svg)](https://github.com/dev-prathap/ATTEST/actions/workflows/ci.yml) [![pypi](https://img.shields.io/pypi/v/attestlayer?label=pypi%20attestlayer)](https://pypi.org/project/attestlayer/) [![npm](https://img.shields.io/npm/v/attestlayer?label=npm%20attestlayer)](https://www.npmjs.com/package/attestlayer) [![docs](https://img.shields.io/badge/docs-dev--prathap.github.io%2FATTEST-black)](https://dev-prathap.github.io/ATTEST/) [![license](https://img.shields.io/badge/license-MIT-green)](./LICENSE)

**Decide → Gate → Verify → Attest.** Your agent sends the email, updates the CRM, moves the money.
Attest decides whether it may, gates it behind a human when it matters, reads back from the system of
record to check it actually happened, and records tamper-evident evidence either way.

Attest never executes your action. Your tool does. That is why it works with any app and any framework
on day one.

## Your agent says it worked. Did it?

Two identical CRM writes, both reported success by the tool, both approved by a human:

```console
$ attest ledger
#2  2026-09-19 10:16:46  someweirdcrm.create → leads   ask  approved  unverified   a09e7641db12
#1  2026-09-19 10:16:46  someweirdcrm.create → leads   ask  approved  verified     77a6d99a60f6
```

The second one read back clean. The first did not, and the ledger says which field disagreed:

```json
{ "level": "unverified", "matched": false,
  "evidence": { "compared": 4, "exists": true, "failed": ["stage"],
    "fields": { "stage": { "want": "qualified", "got": "new", "ok": false } } } }
```

A trace would have shown two green steps. That gap is the entire product.

## Install

```bash
pip install attestlayer          # Python
npm  install attestlayer         # TypeScript — byte-identical ledger format
```

```python
import attest

@attest.action(system="gmail", verb="send", target="to")
def send_email(to, subject, body): ...
```

```ts
import { Attest } from "attestlayer";

const at = new Attest({ agent: "followup-agent@v3", readers: { gmail: process.env.GMAIL_TOKEN! } });
const sendEmail = at.wrap({ system: "gmail", verb: "send", target: "to" },
                          async ({ to, subject, body }) => gmail.send({ to, subject, body }));
```

That is the whole change. The first external send now pauses for a human, and the ledger row says
`acknowledged`, or `verified` once Attest can read back with the agent's own credentials
(`Attest(readers={"gmail": service})`). Nothing else in your code moves.

## Verification is layered, and it never overstates

Every row states exactly how much was checked. A check that could not run is never dressed up as a pass.

| level | what it means |
| --- | --- |
| `verified` | read back from the system of record, and the fields matched |
| `verified-custom` | your own check ran and passed |
| `acknowledged` | the action was accepted, but no read-back could run here |
| `attested-only` | recorded with no verifier available for this action |
| `unverified` | a check ran and **contradicted** the claim |

Only a contradiction earns `unverified`. Missing credentials, a read-only scope or an unsupported verb
degrade to `acknowledged`, because "we could not check" and "it did not happen" are different facts.

## Where it plugs in

| surface | how |
| --- | --- |
| Decorator / wrapper | `@attest.action(...)` · `at.wrap(...)` |
| LangGraph | tool node wrapper, gate as a graph interrupt |
| OpenAI Agents · Claude Agent SDK · CrewAI · DeerFlow | adapters in [`attest/`](./attest/) |
| MCP | zero-code proxy in front of any server, plus a verify server |
| HTTP gateway | point outbound traffic at it, no SDK at all |
| API only | POST the descriptor yourself |

Human confirmation lands where the team already works: Slack, the web inbox, a webhook, a LangGraph
interrupt, or the console. Approvers can edit the parameters before approving, and the edit is recorded.

## The record itself

Hash-chained ledger, SQLite locally and Postgres per organisation in the cloud. Signed checkpoints let
you prune old rows and still verify the chain. Optional Ed25519 signing, and external anchoring to a
file, a git repo or an HTTP endpoint. Exports: JSON, CSV, the IETF `draft-sharif-agent-audit-trail`
JSONL format, and an EU AI Act event-log pack.

Overhead is roughly a sixth of a millisecond per action, measured in
[benchmarks/](./benchmarks/) ([published numbers](https://dev-prathap.github.io/ATTEST/performance/)).

## Try it locally

```bash
python examples/unknown_app.py                         # an app Attest has never seen, L1 → L3
ATTEST_AUTO_APPROVE=1 python examples/langgraph_agent.py
cd deploy && cp .env.example .env && docker compose up  # cloud API :8400 + dashboard :3400
```

## Attest Cloud

The SDK is MIT and works standalone with a local ledger. Attest Cloud adds the shared ledger, the
confirm inbox, versioned org policy, agent keys and compliance exports. Your vendor tokens never reach
it: read-back happens in your process with your own credentials, and only hashes and previews are sent.
Self-host it from [`deploy/`](./deploy/), or read [DEPLOY.md](./DEPLOY.md).

## Install channels

| where | how |
| --- | --- |
| PyPI | `pip install attestlayer` → `attest`, `attest-mcp`, `attest-mcp-server`, `attest-gateway` |
| npm | `npm install attestlayer` |
| MCP Registry | `io.github.dev-prathap/attest` (verify server) · `io.github.dev-prathap/attest-proxy` (zero-code proxy) |
| Smithery | [`attestlayer/attest`](https://smithery.ai/server/attestlayer/attest) |
| Claude Desktop | `attest-<version>.mcpb` on the [latest release](https://github.com/dev-prathap/ATTEST/releases/latest) |
| Docker | `ghcr.io/dev-prathap/attest-api` · `ghcr.io/dev-prathap/attest-dashboard` |

<!-- mcp-name: io.github.dev-prathap/attest -->
<!-- mcp-name: io.github.dev-prathap/attest-proxy -->

## Documentation

Full docs at **[dev-prathap.github.io/ATTEST](https://dev-prathap.github.io/ATTEST/)** —
[quickstart](https://dev-prathap.github.io/ATTEST/quickstart/) ·
[verification levels](https://dev-prathap.github.io/ATTEST/levels/) ·
[policy](https://dev-prathap.github.io/ATTEST/policy/) ·
[read-back recipes](https://dev-prathap.github.io/ATTEST/recipes/) ·
[ledger & exports](https://dev-prathap.github.io/ATTEST/ledger/) ·
[hardening](https://dev-prathap.github.io/ATTEST/hardening/)

## Repository

| path | what |
| --- | --- |
| [attest/](./attest/) | Python SDK — descriptor, policy, ledger, verification ladder, gates, adapters, MCP proxy, CLI |
| [packages/attest-ts/](./packages/attest-ts/) | TypeScript SDK — same canonical hashes, fixture-tested against Python |
| [cloud/](./cloud/) | Attest Cloud — FastAPI + Postgres: orgs, keys, policy versions, ledger, confirm inbox, exports |
| [dashboard/](./dashboard/) | Next.js dashboard — ledger drill-down, confirm inbox, policy and keys |
| [examples/](./examples/) | unknown app, LangGraph, OpenAI Agents, MCP config, API-only, cloud |
| [deploy/](./deploy/) | Dockerfiles and compose |
| [benchmarks/](./benchmarks/) | what the layer costs per action |
| [docs/](./docs/) | documentation site source, plus design notes |

```bash
pytest -q && (cd cloud && pytest -q)     # 355 + 37 offline tests
pytest tests/live                        # 8 live suites; need real credentials, skipped without them
```

## Contributing

Read-back recipes are the easiest place to start: each one teaches Attest how to confirm a write in one
more app, and needs nothing but that app's read API. See [CONTRIBUTING.md](./CONTRIBUTING.md), and
[SECURITY.md](./SECURITY.md) for reporting a vulnerability.

## Principles

- We never execute your action. Your tool executes; we decide, gate, verify and record.
- Coverage is universal. Verification depth is layered and stated honestly on every row.
- Open-source SDK under MIT. Paid cloud for the shared ledger, inbox, policy and exports.

## Design notes

The thinking behind the product, kept in the open: [vision](./docs/01-vision.md) ·
[product](./docs/02-product.md) · [universal adapter](./docs/03-universal-adapter.md) ·
[architecture](./docs/04-architecture.md) · [market](./docs/05-market-positioning.md) ·
[build plan](./docs/06-build-plan.md) · [decisions](./docs/07-decisions.md) ·
[phase plan](./docs/08-phase-plan.md)

## Lineage

Attest's core mechanisms are extracted from two working codebases: **DO** (policy engine, read-back
verification pairs, evidence ledger) and **DeerFlow** (tool receipts, verification patterns, MCP and
chat-channel adapters), which run against real Gmail, Slack, HubSpot, Notion, Linear and Google
Workspace. Attest ships its own live suites for those systems in [`tests/live/`](./tests/live/); they
need real credentials and are skipped without them.
