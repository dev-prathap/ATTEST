# 05 — Market & Positioning

## Category
**Agent accountability / proof layer** — inside the broader "agent execution infrastructure" category.

## Why now (Sept 2026)
- **Capital is moving here.** Agent execution infrastructure (runtimes, sandboxes, identity, observability, control layers) took ~20.7 % of 2026 YTD agent deals. Arcade.dev raised a **$60 M Series A** (June 2026, $72 M total; SYN, Morgan Stanley, Wipro) for a "secure action layer" — *prove which agent took which action, on behalf of which user.*
- **Regulation creates a deadline.** The EU AI Act mandates automatic event logging for high-risk AI systems from **August 2026**. An IETF draft (agent audit trail) is defining the log format. Gartner puts AI-governance spend at ~$492 M in 2026, >$1 B by 2030.
- **Enterprises are blocked on proof.** The stated wall is not "can the agent act" but "can we see and prove what it did."

## Landscape

| Player | What they own | Where Attest sits |
| --- | --- | --- |
| **Arcade** ($72 M) | authorization: *may* the agent act, as whom; logs | before the action. Attest is *after*: did it happen, prove it. Complementary; partner target. |
| **Composio / Nango / MCP servers** | connectors, execution | they execute; we wrap. Customers keep them. |
| **Guardrails (NeuralTrust, etc.)** | content filtering, prompt safety | text; we judge actions and outcomes |
| **Observability (AgentOps, Langfuse, Maxim)** | traces of what the model did | model-side; we verify world-side |
| **Frameworks (LangGraph, OpenAI Agents, DeerFlow)** | run the agent | adapters; DeerFlow has receipts, no read-back |

**Whitespace:** nobody sells *proof of outcome* — read-back verification + tamper-evident evidence — as a drop-in for any framework. Authorization companies stop at "allowed and logged"; we finish with "verified."

## Positioning
- **Promise:** Prove what your AI agent actually did.
- **One-liner:** The accountability layer for agent actions — decide, gate, verify, attest.
- **Claims that must all be true:** universal (any app/action/framework), honest (levels, never faked), zero-execution (their tools run), evidence-first (every entry exportable).

Messaging we avoid: "guardrails", "agent platform", "connectors", "observability".

## First vertical
**Business-app agents** — email, CRM, calendar, docs, chat, tickets.
- Highest-consequence actions (customer-facing sends, CRM state, calendar invites).
- Deepest existing coverage (DO recipes + policy for exactly these systems).
- Clear buyers: sales / CS / RevOps automation teams, agencies building GTM agents, internal-tools teams.
- Ship Gmail + Slack + HubSpot first; then Calendar, Drive, Notion, Linear.

Expansion verticals: finance (payments, very high risk), DevOps/IT, healthcare admin.

## Go-to-market (developer-led, USD, no sales team)
1. **Open-source launch** — GitHub, Show HN ("Prove what your AI agent actually did"), LangChain/LangGraph integrations, dev Twitter/LinkedIn.
2. **Content with a deadline** — "EU AI Act-compliant agent in 10 minutes" (Aug 2026 mandate), "Why 200 OK is not proof".
3. **Distribution hooks** — MCP `verify` server; `verified-actions` skill on skills marketplaces (Claude Code / Codex / Cursor users); Slack Marketplace confirm-gate app; LangChain integration page.
4. **Cloud conversion** — hosted ledger + Slack confirm from the OSS funnel; usage billing via Stripe.
5. **Partnerships** — Arcade ("authorize with Arcade, verify with Attest"), LangChain, Nango.

## Targets
| Horizon | Goal |
| --- | --- |
| Month 1 | OSS live; 500+ stars; 20 teams trying it |
| Month 3 | Cloud beta; 5 paying teams; $1–3 k MRR |
| Month 12 | $10–30 k MRR; recognized as "the verify layer"; seed / partnership conversations |

## Sources
- Arcade $60 M Series A — BusinessWire (2026-06-15); SiliconANGLE; The Next Web
- EU AI Act logging obligations — miniOrange "Enterprise guide to AI agent audit trails 2026"; NeuralTrust 2026 guide
- IETF draft-sharif-agent-audit-trail
- Agentic AI funding trends 2026 — New Market Pitch
- Solo/indie SaaS benchmarks 2026 — SoftwareSeni, BigIdeasDB
- Skills marketplaces 2026 — Agensi guides
