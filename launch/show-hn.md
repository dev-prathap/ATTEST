# Show HN draft

**Title:** Show HN: Attest – prove what your AI agent actually did (open-source, MIT)

**Body:**

Hi HN. I'm Prathap. I built Attest because every agent framework makes it trivial to give an agent tools, and
none of them can answer the question a company asks before letting agents act: *did it actually happen, and
can we prove it?*

"The API returned 200" is not proof. A 200 from a mail API doesn't mean the mail reached the right recipient.
A 200 from a CRM doesn't mean the field holds the value you intended. Teams find the gap in an incident, an
audit, or a customer complaint.

Attest is a small layer around the action:

- **Decide** — a policy engine returns act / ask / refuse with a risk tier and reasons. Recipients are classified
  internal / known / external; deletes and payments ask; unknown writes ask.
- **Gate** — risky actions wait for a human where the team already works: Slack card, web inbox, webhook, or the
  framework's own pause (LangGraph interrupt, MCP pending + resume token).
- **Verify** — after *your* tool runs, Attest reads back from the system of record with *your* credentials and
  compares intent with what's there. The result is a level, never a boolean: verified / verified-custom /
  acknowledged / attested-only / **unverified** (the API said yes, the record disagrees).
- **Attest** — one hash-chained ledger row per action. Params and results are stored as hashes plus an
  allow-listed preview, never bodies.

It never executes anything — that's why it's universal on day one. One decorator, a LangGraph / OpenAI Agents
wrapper, or a zero-code MCP proxy (`attest-mcp --upstream <your server>`) that verifies `create_issue` by calling
`get_issue`. An app it has never seen (`POST api.someweirdcrm.io/v2/leads`) is still recorded, decided, gated,
and — via `GET /v2/leads/{id}` — verified.

Repo: https://github.com/dev-pratapk/ATTEST · Docs: <docs url> · `pip install attestlayer`

What I'd love feedback on: the verification ladder's honesty rules (a check that *can't* run degrades, only a
contradiction is `unverified`), the read-back recipes you'd want next, and whether the MCP proxy approach
makes sense for your stack.

*(Lineage: the policy engine and read-back pairs were extracted from a working internal product that runs
against real Gmail, Slack, HubSpot, Notion and Linear. Nothing here is theoretical.)*
