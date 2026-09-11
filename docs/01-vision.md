# 01 — Vision

## The one line
> **Prove what your AI agent actually did.**

## The problem
Agents have crossed from *answering* to *acting*: they send email, update CRMs, create tickets, share documents, move money. Every framework makes it easy to give an agent tools. None of them can answer the three questions a company must answer before it lets agents act at scale:

1. **Should this action happen at all?** (policy — who, what, to whom, how risky)
2. **Did a human approve the ones that matter?** (gate)
3. **Did it actually happen, and can we prove it?** (verification + evidence)

Today the answer is "the API returned 200" — which is not proof. A 200 from a mail API does not mean the mail reached the right recipient. A 200 from a CRM does not mean the field holds the intended value. Teams discover the gap in an incident, an audit, or a customer complaint.

## The thesis
Everything around the action is becoming a commodity — the model, the framework, the connectors, the sandbox. **The trust boundary around the action is not.** The layer that decides, gates, verifies and attests is small, universal, and must sit in front of every agent that touches a system of record. Whoever owns that layer owns the agent's *accountability*.

Attest owns that layer.

## What Attest is
An **accountability layer** for agent actions:

```
Decide   → policy engine: act | ask | refuse, with a risk tier and reasons
Gate     → human confirmation for actions that warrant it, in Slack/web/API
Verify   → read-back from the system of record: did it really happen?
Attest   → tamper-evident evidence ledger, exportable for audit and regulation
```

It is delivered as an **open-source SDK** (one decorator, one adapter, or zero-code proxy) plus a **hosted cloud** (ledger, confirm inbox, policies, exports, billing).

## What Attest is not
- Not an agent framework (LangGraph, OpenAI Agents, CrewAI, DeerFlow run the agent; we wrap its actions)
- Not a connector / action platform (Composio, Nango, Arcade, MCP servers execute; we do not)
- Not a guardrail / content filter (we judge *actions* and their *outcomes*, not text)
- Not observability / tracing (traces show what the model *said*; we prove what the world *did*)

Those may all exist underneath or beside Attest. They are not the product.

## Why we win
1. **We do not execute.** Because the customer's tool executes, we owe no connectors and can be universal on day one. Execution platforms must build 1,000 connectors to claim "all apps"; we claim it structurally.
2. **Verification is the whole point.** Authorization asks "may it?"; we ask "did it?" — with evidence. Nobody sells proof of outcome as a drop-in.
3. **Honesty is a feature.** Every ledger entry carries its verification level (`verified`, `acknowledged`, `attested-only`). We never fake certainty.
4. **It already works.** Policy, read-back pairs, evidence ledger and OAuth handling are extracted from DO, where they run against real systems today.

## The ultimate experience
A team ships an agent. They add one line. From then on:
- risky actions wait for a person, in the tool the team already uses;
- every action has a receipt that says *verified* or *not*;
- an auditor, a customer, or a regulator gets a signed export in one click;
- nothing about how the team built the agent had to change.

**An agent should not be allowed to act unless someone can prove what it did.** Attest makes that the default.
