# Attest

> **Prove what your AI agent actually did.**

Agents send email, update CRMs, create tickets, share documents, move money. Every framework makes it easy to
give an agent tools. None can answer the three questions a company must answer before it lets agents act:

1. **Should this action happen at all?** — policy
2. **Did a human approve the ones that matter?** — gate
3. **Did it actually happen, and can we prove it?** — verification + evidence

Today the answer is "the API returned 200", which is not proof. Attest is the layer that turns it into proof.

```
Decide   → policy engine: act | ask | refuse, with a risk tier and reasons
Gate     → human confirmation where the team already works: Slack, web inbox, webhook
Verify   → read-back from the system of record: did it really happen?
Attest   → tamper-evident, hash-chained ledger; exportable for audit
```

**One line, any framework, any app.** Attest never executes the action — your tool does. That is why it is
universal on day one. Verification depth is layered and honest: every ledger entry says exactly how much was
checked.

```python
import attest

@attest.action(system="gmail", verb="send", target="to")
def send_email(to, subject, body): ...
```

[Quickstart →](quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/dev-pratapk/ATTEST){ .md-button }

## What it is not

Not an agent framework. Not a connector platform. Not a guardrail / content filter. Not tracing. Those run the
agent, execute the action, judge the text, or show what the model *said*. Attest proves what the world *did*.
