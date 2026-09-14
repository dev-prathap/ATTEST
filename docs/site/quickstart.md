# Quickstart — 5 minutes, no cloud

```bash
pip install attest          # from the repo today: pip install -e ".[dev]"
```

## 1. Wrap one function

```python
import attest

@attest.action(system="gmail", verb="send", target="to")
def send_email(to, subject, body):
    return gmail.users().messages().send(userId="me", body=msg).execute()

send_email("arun@newco.com", "Follow-up", "…")
```

The first external send **pauses**: the console asks `y / n / e`. Approve it.

## 2. Look at the ledger

```bash
attest ledger
attest verify          # hash chain intact
```

```
#1  2026-09-15 10:02:11 gmail.send → arun@newco.com  ask  approved  acknowledged  5b1c…
```

`acknowledged` means the API returned an id and nothing was read back. Give Attest the client the agent
already holds and it reads the message back and compares recipients, subject and the SENT label:

```python
at = attest.Attest(readers={"gmail": gmail})     # or an OAuth token string
```

```
#2  … gmail.send → arun@newco.com  ask  approved  verified  …
```

## 3. Set one policy

`attest.yaml`:

```yaml
policies:
  - match: { verb: [send, share], target: external }
    decision: ask
  - match: { verb: [delete, pay] }
    decision: ask
  - match: { system: hubspot, verb: update }
    decision: act
```

## 4. Don't label anything

```python
@attest.action                                                   # send_email ⇒ unknown / send
def send_email(to, body): ...

@attest.action(method="POST", url="https://api.someweirdcrm.io/v2/leads")   # ⇒ someweirdcrm / create
def create_lead(name, email): ...
```

An app Attest has never seen is still recorded, decided, gated, and — with `http_get=` — read back by
convention (`GET /v2/leads/{id}`) and **verified**. Run `examples/unknown_app.py` to see all three rungs.

## 5. Whole agent, one line

=== "LangGraph"
    ```python
    from attest.adapters import langgraph as attest_lg
    tools = attest_lg.wrap_tools(tools, at, mapping={"send_email": {"system": "gmail", "verb": "send", "target": "to"}})
    ```
=== "OpenAI Agents"
    ```python
    from attest.adapters import openai_agents as attest_oa
    tools = attest_oa.wrap_tools(tools, at, mapping=mapping)
    ```
=== "MCP (zero code)"
    ```json
    { "mcpServers": { "gmail": { "command": "attest-mcp",
        "args": ["--upstream", "npx -y @modelcontextprotocol/server-gmail", "--server", "gmail"] } } }
    ```

Nothing about how you built the agent changed.
