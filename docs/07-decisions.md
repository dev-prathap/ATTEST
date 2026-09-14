# 07 — Decisions

## Locked
| # | Decision | Why |
| --- | --- | --- |
| 1 | **Name: Attest** (working; rename allowed before launch) | states the promise in one word |
| 2 | **Wrapper model — we never execute** the customer's action | universality without connectors; no competition with execution platforms; safer |
| 3 | **Universal coverage day one** (descriptor + verb detection + L0 floor) before deep recipes | nobody is turned away; depth is layered |
| 4 | **Verification levels, never a boolean**; `unverified` is first-class | honesty is the product's trust |
| 5 | **Python SDK first**, TypeScript second; MCP proxy + HTTP gateway + API keep everything else language-agnostic | largest agent-builder base today |
| 6 | **First reviewed recipes: Gmail, Slack, HubSpot**; then Calendar, Drive, Notion, Linear, M365 | highest-consequence actions; DO coverage exists |
| 7 | **Pass-through auth by default**; Nango only as optional cloud mode | never block adoption on our OAuth; tokens stay in the customer's process |
| 8 | **OSS SDK (MIT) + paid cloud** | developer-led USD go-to-market; cloud = ledger, confirm, policies, exports |
| 9 | **First vertical: business-app agents** (email · CRM · calendar · docs · chat · tickets) | consequence, coverage, clear buyers |
| 10 | **Lineage: extract from DO + DeerFlow**; no rewrite from scratch | mechanisms already run against real systems |
| 11 | **Developer-led, self-serve, no enterprise sales in year one** | founder is solo, India-based; USD via self-serve |
| 12 | **Ledger is append-only and hash-chained per org** | tamper-evidence is the whole point of "attest" |

## Open (resolve during Phase 1)
- Final product name and domain.
- Cloud auth provider: keep DO's Better Auth vs. WorkOS/Clerk. *(v0 ships API keys with roles — agent / approver / admin — and no user login; the dashboard authenticates with a key. Decide before public cloud beta.)*
- Params storage default: hash-only vs. allow-listed preview (leaning hash + preview).
- Exact usage-pricing unit: per verified action vs. per attested action.
- Whether the MCP proxy also serves as the HTTP gateway (single binary) in Phase 3.
- Signed-ledger anchoring (external timestamping) — Phase 3 or later.

## Explicitly rejected
- Building an action/connector platform (Arcade/Composio territory).
- Content guardrails as a feature.
- "Verified" without read-back or custom check.
- Marketing as an "agent platform", "guardrails", or "observability".
