# Ledger & exports

Append-only SQLite, one row per action, hash-chained: each hash covers the canonical payload and the previous
hash, so editing, deleting or reordering any row breaks verification from that row on.

```python
from attest import SqliteLedger
L = SqliteLedger(".attest/ledger.sqlite")
L.entries(run_id="…", level="unverified")
L.verify_chain()          # ChainReport(ok, checked, broken_at, problems)
L.export("json") / L.export("csv")
```

What a row holds: action id, run, agent, actor, descriptor (system, verb, target, target class, source,
`params_hash`), allow-listed params preview, decision, risk tier, reasons, rules fired, confirm record
(status, channel, approver, decided at, edits), execution (status, result hash, preview, error, duration),
verification (level, method, matched, evidence), `resumed_from` when it completes a pending row, and the chain
fields (`seq`, `prev_hash`, `payload_hash`, `hash`).

Raw params and results never enter the ledger. Previews are allow-listed keys (recipients, ids, subjects,
names); bodies never.

Attest Cloud keeps a second, per-org chain over the same payloads and exports a signed manifest
(`GET /v1/export`). IETF agent-audit-trail and EU AI Act event-log packs arrive in Phase 2.
