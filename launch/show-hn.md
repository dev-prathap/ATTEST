# Show HN draft

**Status before posting:** ☐ PyPI published · ☐ `pytest tests/live` green (then delete the caveat line below)
· ☐ docs URL correct · ☐ repo public

**Title:** Show HN: Attest – prove what your AI agent actually did (MIT)

**Body:**

Hi HN. I'm Prathap. Every agent framework makes it easy to give an agent tools. None of them can answer the
question a company asks before letting agents act: *did it actually happen, and can we prove it?*

"The API returned 200" is not proof. A 200 from a mail API doesn't mean the mail reached the right recipient. A
200 from a CRM doesn't mean the field holds the value you intended. Teams find the gap in an incident, an audit,
or a customer complaint.

Attest is a small layer around the action:

- **Decide** — a policy engine returns act / ask / refuse with a risk tier and reasons. Recipients are classified
  internal / known / external; deletes and payments ask; unknown writes ask.
- **Gate** — risky actions wait for a human where the team already works: Slack card, web inbox, webhook, email,
  or the framework's own pause (LangGraph interrupt, MCP pending + resume token).
- **Verify** — after *your* tool runs, Attest reads back from the system of record with *your* credentials and
  compares intent with what is there. The result is a level, never a boolean: verified / verified-custom /
  acknowledged / attested-only / **unverified** (the API said yes, the record disagrees).
- **Attest** — one hash-chained ledger row per action. Params and results are stored as hashes plus an
  allow-listed preview, never bodies.

It never executes anything — that is why it is universal on day one. One decorator, a LangGraph / OpenAI Agents /
Claude Agent SDK / CrewAI wrapper, a Vercel AI SDK / LangChain.js / Mastra wrapper in TypeScript, an HTTP gateway
you point a base URL at, or a zero-code MCP proxy (`attest-mcp --upstream <your server>`) that verifies
`create_issue` by calling `get_issue`. An app it has never seen (`POST api.someweirdcrm.io/v2/leads`) is still
recorded, decided, gated, and — via `GET /v2/leads/{id}` — verified.

```ts
import { Attest } from "attestlayer";
const at = new Attest({ readers: { gmail: GMAIL_TOKEN } });
const send = at.wrap({ system: "gmail", verb: "send", target: "to" }, async ({ to, subject, body }) => gmail.send(…));
```

TypeScript is on npm today (`npm install attestlayer`); the Python SDK is the same contract and the same ledger
format — a ledger written by one verifies with the other, asserted by a byte-for-byte hash fixture in CI.

*(Caveat while it is true: the read-back recipes are covered by tests against client-shaped fakes; the live-account
suite exists but has not been run against production Gmail / Slack / HubSpot yet. I would rather say that than
imply otherwise.)*

Repo: https://github.com/dev-prathap/ATTEST · Docs: https://dev-prathap.github.io/ATTEST/

What I'd love feedback on: the verification ladder's honesty rules (a check that *can't* run degrades, only a
contradiction is `unverified`), which read-back recipes you'd want next, and whether the MCP proxy approach fits
your stack.
