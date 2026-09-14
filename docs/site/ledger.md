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

## Checkpoints and retention

```bash
ATTEST_LEDGER_KEY=… attest checkpoint          # HMAC-signed (seq, hash, signed_at) pinned in the ledger
attest prune --older-than-days 30              # drops old rows behind a checkpoint; the chain still verifies
```

A checkpoint pins the head at a moment in time. Retention prunes rows *before* a checkpoint and verification
resumes from it, so a 30-day ledger is still tamper-evident end to end. The cloud does the same per org
(`POST /v1/ledger/checkpoint`, `POST /v1/ledger/prune`, `retention_days` setting, `ATTEST_SIGNING_KEY`).

## Exports

| format | what |
| --- | --- |
| `json` | entries + manifest (cloud: signed) |
| `csv` | one row per action |
| `ietf` | JSONL records per the IETF agent-audit-trail draft: `record_id`, `timestamp`, `agent_id`, `session_id`, `action_type`, `action_detail`, `outcome`, `trust_level` (L0–L3), `parent_record_id`, `prev_hash`, `record_phase`, `human_override`, `input_hash`, `output_hash`, `deny_reasons` |
| `eu-ai-act` | event-log pack: system identification, period, per-event records with human oversight and outcome verification, integrity (chain, checkpoints), a field map to Article 12-style expectations, signed manifest. An engineering aid, not legal advice. |

`attest export --format ietf` · `GET /v1/export?format=eu-ai-act` · dashboard → Ledger → export links.
