# Show HN draft

**Before posting:** ☐ `pytest tests/live --live-report` green (then delete the caveat paragraph from
[show-hn-comment.txt](./show-hn-comment.txt)) · ☐ links open in a private window · ☐ you are free for the next
three hours to answer comments
**Best window:** weekday, 8–10am US Eastern (5:30–7:30pm IST), Monday to Wednesday.

**How to post:** submit the title and URL below at news.ycombinator.com/submit, leave the text field empty —
HN ignores it when a URL is given — then immediately paste [show-hn-comment.txt](./show-hn-comment.txt) as the
first comment on your own post. That file is plain text on purpose: HN renders no Markdown, and joins lines
within a paragraph, so bullets and bold from the draft below would collapse into a wall of text.

---

**Title:** Show HN: Attest – prove what your AI agent actually did

**URL:** https://github.com/dev-prathap/ATTEST

**Body:**

Hi HN. I'm Prathap. Every agent framework makes it easy to give an agent tools. None of them answers the
question a company asks before letting agents act: *did it actually happen, and can we prove it?*

"The API returned 200" is not proof. A 200 from a mail API doesn't mean the mail reached the right recipient. A
200 from a CRM doesn't mean the field holds the value you intended. Teams find the gap in an incident, an audit,
or a customer complaint.

Attest is a small layer around the action:

- **Decide** — a policy engine returns act / ask / refuse with a risk tier and reasons. Recipients are classified
  internal / known / external; deletes and payments ask; unknown writes ask.
- **Gate** — risky actions wait for a human where the team already works: Slack card, web inbox, webhook, email,
  Teams, or the framework's own pause (LangGraph `interrupt`, MCP pending + resume token).
- **Verify** — after *your* tool runs, Attest reads back from the system of record with *your* credentials and
  compares intent with what is there. The result is a level, never a boolean: `verified` / `verified-custom` /
  `acknowledged` / `attested-only` / **`unverified`** — the API said yes and the record disagrees.
- **Attest** — one hash-chained ledger row per action. Params and results are stored as hashes plus an
  allow-listed preview, never bodies.

It never executes anything. That is why it works with any stack on day one, and why it owes no connectors:

```python
@attest.action(system="gmail", verb="send", target="to")
def send_email(to, subject, body): ...        # your code; Attest decides, gates, reads back, records
```

Also: LangGraph / OpenAI Agents / Claude Agent SDK / CrewAI wrappers, a TypeScript SDK with Vercel AI SDK,
LangChain.js and Mastra adapters, an HTTP gateway you point a base URL at, and a zero-code MCP proxy —
`attest-mcp --upstream <your server>` verifies `create_issue` by calling `get_issue`. An app it has never seen
(`POST api.someweirdcrm.io/v2/leads`) is still recorded, decided, gated, and — via `GET /v2/leads/{id}` —
verified.

Two design choices I'd defend:

1. **Levels, not booleans.** A check that *cannot* run (network error, missing id, no recipe) degrades to
   `acknowledged` with the error in evidence. Only a contradiction is `unverified`. A read-back that finds the
   record but has nothing comparable is `acknowledged` with `exists: true` — never `verified`. The ledger never
   claims more than it checked.
2. **Nothing leaves your process.** Read-back uses the credential the agent already holds. The hosted option
   stores hashes and previews; vendor tokens never reach it.

Install: `pip install attestlayer` · `npm install attestlayer` · MCP registry `io.github.dev-prathap/attest`
· Smithery `attestlayer/attest`. Docs: https://dev-prathap.github.io/ATTEST/

*(Caveat while true: the recipes are covered by tests against client-shaped fakes and the ledger's tamper
behaviour is tested directly, but the live-account suite has not yet been run against production Gmail / Slack /
HubSpot. I'd rather say that than imply otherwise.)*

MIT. What I'd like feedback on: the honesty rules above, which read-back recipes you'd want next, and whether
the MCP proxy fits how you actually run agents.

---

## Comment replies to have ready

**"Isn't this just observability / tracing?"** Traces show what the model said and which tool it called. They
never look at the world afterwards. Attest compares your intent with what the system of record holds, and says
so per action.

**"Why not let the framework do it?"** Frameworks will add human-in-the-loop. Few will add read-back, because
read-back needs per-system knowledge — which read proves which write — and that knowledge is identical across
frameworks. It belongs in one layer in front of everything that touches a system of record.

**"What about actions with no read?"** They stay `acknowledged` or `attested-only`, labelled as such. Coverage
is 100%, depth is honest. You can always supply `verify=` yourself.

**"How is the ledger tamper-evident if I control the database?"** Each row's hash covers its payload and the
previous hash. Signed checkpoints pin the head; anchoring publishes a checkpoint to somewhere you don't control
(a git repo, an append-only file, a timestamping service). After that, rewriting history is detectable.

**"Does it slow the agent down?"** One read per write, in-process, with the credential you already hold. Gating
only happens when policy says ask.

**"Performance / scale numbers?"** A whole action — detect, policy, gate check, ledger append with the hash
chain — is about 164 µs mean on Apple silicon, dominated by the SQLite write. Read-back adds one HTTP round trip
to the system of record, 50–300 ms typically; that is the real price of `verified` and it dwarfs the layer.
Chain verification is linear: 10k rows in 347 ms, or 2.2 ms from the newest checkpoint. Numbers and the script:
https://dev-prathap.github.io/ATTEST/performance/

**"Who are you / is this a company?"** Solo, built in the open, MIT. The hosted piece exists so teams can share
a ledger and an approval inbox; the SDK is complete without it.
