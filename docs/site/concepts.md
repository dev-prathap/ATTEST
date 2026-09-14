# The four steps

Every action — a decorated function, a LangGraph tool, an MCP `tools/call`, a REST request — is normalized to
one **Action Descriptor**:

```json
{ "system": "gmail", "verb": "send", "target": "arun@newco.com",
  "params_hash": "…", "actor": "ram@acme.com", "agent": "followup-agent@v3", "run_id": "…" }
```

Policy, gate, verify and ledger operate only on this shape. Supporting a new framework or app means mapping
to the descriptor; the core never changes.

## Decide
The policy engine returns `act`, `ask` or `refuse` with a risk tier and reasons. Built-in rules run first:
org rule (blocked / approval required), acting on another's connection, recipient legitimacy
(internal / known / external), unfilled placeholders, risk tier. Then your YAML, first match wins.
Authority comes from a human's out-of-band confirmation, never from message content.

## Gate
`ask` pauses the action where the team already works: console, Slack card, web inbox, webhook — or the
framework's native mechanism (LangGraph `interrupt`, MCP pending + resume token). Approval, rejection and
edits are recorded with the approver's identity.

## Verify
After **your** tool executes, Attest reads back from the system of record with **your** credentials and
compares intent with what is there. The result is a [level](levels.md), never a boolean.

## Attest
Every action becomes one hash-chained ledger entry: descriptor, params hash and allow-listed preview, decision
trail, confirm record, execution result hash, verification level and evidence. Raw params and results never
enter the ledger.
