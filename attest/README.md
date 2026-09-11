# attest (Python SDK)

Decide → Gate → Verify → Attest, for any function that makes an agent act.

```bash
pip install -e ".[dev]"      # from the repo root
pytest -q
ATTEST_AUTO_APPROVE=1 python examples/unknown_app.py
```

## Quickstart

```python
import attest

@attest.action(system="gmail", verb="send", target="to")
def send_email(to, subject, body):
    return gmail.users().messages().send(userId="me", body=...).execute()

send_email("arun@newco.com", "Follow-up", "…")
```

What happens on that call:

1. **Decide** — the call becomes an Action Descriptor (`gmail.send` → `arun@newco.com`). Built-in rules
   classify the recipient as external and the default policy says `ask`.
2. **Gate** — the console prompts `y / n / e`. `ATTEST_AUTO_APPROVE=1` approves in CI; a non-interactive
   stdin rejects. Slack and web inbox arrive in P1.3.
3. **Execute** — your function runs. Attest never calls the vendor to write.
4. **Verify** — the response carried an id ⇒ `acknowledged` (L1). Pass `verify=` for your own check (L2).
   Read-back recipes (L3) arrive in P1.2.
5. **Attest** — one hash-chained row in `.attest/ledger.sqlite` (or `$ATTEST_LEDGER`), with params and result
   stored as hashes plus an allow-listed preview.

Nothing about how you built the agent changed.

## Detection without labels

```python
@attest.action                                                   # send_email ⇒ unknown / send
def send_email(to, body): ...

@attest.action(method="POST", url="https://api.someweirdcrm.io/v2/leads")   # ⇒ someweirdcrm / create
def create_lead(name, email): ...

@attest.action(tool_name="hubspot_update_deal")                  # ⇒ hubspot / update
def update_deal(deal_id, **props): ...

attest.register("acme_internal_tool", system="acme", verb="pay") # your own override
```

## Policy (YAML)

`$ATTEST_POLICY` or `./attest.yaml`; first match wins; built-in rules R0–R4 run first.

```yaml
policies:
  - match: { verb: [send, share], target: external }
    decision: ask
  - match: { verb: [delete, pay] }
    decision: ask
    approvers: [finance-leads]
  - match: { system: hubspot, verb: update }
    decision: act
  - match: { target_domain: [competitor.com] }
    decision: refuse
```

Match keys: `system`, `verb`, `target` (internal | known | external | none), `target_domain`, `actor`, `agent`,
`risk`, `action` (`gmail.send`, globs allowed). Decisions: `act`, `ask`, `refuse`.

## Verification levels

| level | meaning |
| --- | --- |
| `verified` | read-back recipe matched (P1.2) |
| `verified-custom` | your `verify=` returned true |
| `acknowledged` | response carried an id / success — the API said yes, nothing was read back |
| `attested-only` | recorded; nothing checkable |
| `unverified` | a check ran and **contradicted** the claimed result |

A check that could not run (exception, missing id) degrades to `acknowledged` / `attested-only` with the
error in evidence. Only a contradiction is `unverified`.

## Ledger

```python
from attest import SqliteLedger
L = SqliteLedger(".attest/ledger.sqlite")
L.entries(run_id="…")      # LedgerEntry objects
L.verify_chain()           # ChainReport(ok, checked, broken_at)
L.export("json") / L.export("csv")
```

## API-only (entry point 5)

```python
attest.attest(system="n8n", verb="send", target="x@ext.com", result={"id": "m1"})            # ⇒ acknowledged
attest.attest(system="n8n", verb="send", verified=True, evidence={"message_id": "m1"})       # ⇒ verified-custom
```

## Environment

| var | effect |
| --- | --- |
| `ATTEST_LEDGER` | ledger path (default `.attest/ledger.sqlite`) |
| `ATTEST_POLICY` | policy YAML path |
| `ATTEST_AUTO_APPROVE` | `1` approve all, `0` reject all (skips the console gate) |
| `ATTEST_AGENT`, `ATTEST_ACTOR` | defaults for the descriptor |
