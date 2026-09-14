# Policy

`$ATTEST_POLICY`, `./attest.yaml`, or the org policy in Attest Cloud. First match wins.

```yaml
policies:
  - name: external-send
    match: { verb: [send, reply, share, upload], target: external }
    decision: ask
    reason: reaches someone outside the organisation
  - match: { verb: [delete, pay] }
    decision: ask
    approvers: [finance-leads]
  - match: { system: hubspot, verb: update }
    decision: act
  - match: { system: unknown, verb: [write, execute, approve] }
    decision: ask
  - match: { target_domain: [competitor.com] }
    decision: refuse
  - match: { action: "gmail.*" }
    decision: act
```

**Match keys:** `system`, `verb`, `target` (`internal | known | external | none`), `target_domain`, `actor`, `agent`,
`risk` (`low | medium | high | very_high`), `action` (`gmail.send`, globs allowed). Values may be lists.
**Decisions:** `act`, `ask`, `refuse`. **`approvers`** names who may decide the confirm request — people or groups.

## Approver groups and per-agent overrides

```yaml
groups:
  finance-leads: [priya@acme.com, dev@acme.com]

agents:
  followup-agent@v3:            # evaluated before the global policies, only for this agent
    policies:
      - match: { system: hubspot, verb: update }
        decision: act
```

Groups resolve onto the confirm request (`approver_members`) and appear on the Slack card. Attest Cloud refuses
a decision from anyone outside the group (admins exempt); locally `ConfirmDecision.authorised(request)` gives
custom gates the same check.

## Built-in rules (always first)

| rule | effect |
| --- | --- |
| R0 org rule | `blocked` ⇒ refuse; `approval_required` ⇒ ask (from cloud / `PolicyContext.org_rule`) |
| R1 owner | annotates when the action runs on someone else's connection |
| R2 target | classifies recipients as internal (your domain), known (a relationship), external; YAML decides |
| R3 placeholders | `[NAME]`, `{{first_name}}`, `<FIRST NAME>` in a write ⇒ ask, marked *hold* (fix before it can proceed) |
| R4 risk | no rule matched: low / medium ⇒ act, high / very high ⇒ ask |

Risk by verb: reads low · update/write medium · send/create/share/approve/execute high · delete/pay very high.
Creating or changing a charge, refund, transfer or payout classifies as `pay`. Unrecognised side effects on
unknown systems are `write` at high risk — an unknown write always asks by default.
