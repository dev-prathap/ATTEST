# An EU AI Act-ready event log for your agent in 10 minutes

*Draft blog post. Not legal advice — the Act's obligations depend on your system's classification; talk to
counsel. This post is about the engineering: producing an automatic, tamper-evident record of what an AI system
did, which is what Article 12 (record-keeping / logging) asks of high-risk systems, and what auditors ask of
everyone else.*

## What the Act asks for (engineering view)

High-risk AI systems must be designed for **automatic recording of events** over their lifetime, sufficient to
trace the system's operation, identify situations that may present a risk, and support post-market monitoring.
Providers must keep those logs. Deployers must keep the logs under their control. The practical questions an
auditor will ask:

1. What did the system do, when, on whose behalf?
2. Who approved the consequential actions?
3. Did the action actually take effect, and what is the evidence?
4. Can you show the record has not been altered?

Traces answer (1) for the model. Nothing off-the-shelf answers (2)–(4) for the world.

## Ten minutes

**Minute 1–2. Wrap the actions.**

```python
import attest
@attest.action(system="gmail", verb="send", target="to")
def send_email(to, subject, body): ...
```
or, for a LangGraph agent, `attest_lg.wrap_tools(tools, at, mapping=…)`; for an MCP stack, `attest-mcp`.

**Minute 3–4. Decide what needs a human.** `attest.yaml`:

```yaml
policies:
  - match: { verb: [send, share], target: external }
    decision: ask
  - match: { verb: [delete, pay] }
    decision: ask
    approvers: [finance-leads]
```

**Minute 5–6. Put approvals where the team is.** A Slack card with Approve / Reject; the approver's identity
is recorded. Or the web inbox (`attest serve`). Every decision lands in the ledger with status, approver,
channel, timestamp and any edits.

**Minute 7–8. Turn on read-back.** Give Attest the credentials the agent already holds:

```python
at = attest.Attest(readers={"gmail": gmail_service, "hubspot": hubspot_token})
```
Now each row says `verified` (record matched), `acknowledged` (API said yes, nothing read back), or
`unverified` (contradiction). The ledger never claims more than it checked.

**Minute 9. Verify the chain.**

```bash
attest verify        # chain ok=True entries=1284
```
Each row's hash covers its payload and the previous hash. Edit, delete, or reorder one and verification breaks
from that row on.

**Minute 10. Export.**

```bash
attest export --format json > agent-events.json     # or GET /v1/export on Attest Cloud (signed manifest)
```

## What you have

An automatic, per-action record of: the normalized action (system, verb, target, on whose authority), the
policy decision and reasons, the human approval with identity, the execution outcome, the verification level
with evidence, and a tamper-evident chain — without storing message bodies (params and results are hashed;
previews are allow-listed ids and recipients).

The EU AI Act event-log pack (mapping fields to the Article 12 expectations and the IETF agent-audit-trail
draft) ships in Phase 2. The records it will pack are the ones you start writing today.
