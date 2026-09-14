# Why "200 OK" is not proof

*Draft blog post — ~900 words.*

Your agent just told you it sent the proposal. The tool call returned `{"id": "18f3abc", "threadId": "…"}`.
The trace shows a clean green step. The customer never got the email.

This is not a hypothetical. Mail APIs return an id when the message is *accepted*, not delivered. A CRM
`PATCH` returns 200 when the request was *processed* — including when a workflow rule overwrote your value a
millisecond later. A calendar API creates the event and quietly drops the attendee it could not resolve. Every
one of these returns success. None of them is proof.

## What we usually have

Agent stacks give us three kinds of evidence, and all three are model-side:

1. **The trace** — what the model *said* and which tool it *called*. Observability tools are great at this.
2. **The tool response** — what the vendor *claimed*. A status code, an id, `ok: true`.
3. **The model's summary** — "I sent the email and updated the deal." Generated text.

Nothing here looks at the world after the action. Nothing compares what you *intended* with what the system of
record *holds*.

## What proof looks like

Proof is a read-back. Send the email, then `messages.get` it and check: is `SENT` in its labels, is the
intended recipient actually in the `To` header, is the subject the one you meant? Update the deal, then fetch
it and compare every property you set. Create the lead, then `GET /leads/{id}` and check the fields.

That is the whole idea behind Attest's **verification ladder**:

| level | what it means |
| --- | --- |
| `verified` | read back and matched — recipients, subject, properties, whatever the intent was |
| `verified-custom` | your own check said yes |
| `acknowledged` | the API said yes; nothing was read back — *this is what "200 OK" is worth* |
| `attested-only` | recorded; nothing checkable |
| `unverified` | **a check ran and contradicted the claim** |

Two rules keep it honest. A check that could not run (network error, missing id) is *not* a contradiction —
it degrades to `acknowledged` with the error in the evidence. And a read-back that finds the record but has
nothing to compare is `acknowledged` with `exists: true`, never `verified`. The ledger never claims more than
it checked.

## The incident you want to catch

`unverified` is the level that pays for everything else. It is the moment the vendor said yes and the world
said no: the email that landed in Drafts, the deal stage a workflow reverted, the message posted to the wrong
channel. Today those surface as customer complaints. With a read-back they surface as a red row in the ledger
thirty seconds later, with the field that disagreed.

## Why this has to sit outside the framework

Every framework will eventually add "human in the loop". Few will add read-back, because read-back needs
per-system knowledge (which read proves which write) and that knowledge is the same regardless of framework.
It belongs in one layer that sits in front of every agent that touches a system of record, and that layer
should not execute anything — so it owes no connectors and can be universal from day one.

That layer is what we built. One decorator, or a LangGraph / OpenAI Agents wrapper, or an MCP proxy with zero
code. Reviewed recipes for Gmail, Slack and HubSpot; a convention driver for any REST API (`create` ⇒ `GET
/{id}`); MCP tool pairs (`create_issue` ⇒ `get_issue`). And a hash-chained ledger that stores hashes and
previews, never bodies.

`pip install attest`. Wrap one function. Look at the level next to it.
