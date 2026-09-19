# Performance

What the layer costs per action, with the customer's own tool call stubbed out — so these are Attest's numbers,
not the vendor's latency. Reproduce with `python benchmarks/bench.py`; the raw JSON is in
`benchmarks/results.json`.

Machine: Apple silicon (arm64), Python 3.12, SQLite ledger on tmpfs (`:memory:`), 1000 samples each.

| what | mean | p50 | p95 |
| --- | --- | --- | --- |
| detect system + verb from a tool name | 9.8 µs | 9.7 µs | 10.3 µs |
| detect from method + URL | 10.1 µs | 9.7 µs | 10.2 µs |
| policy evaluate (R0–R4 + rules) | 11.3 µs | 11.0 µs | 12.6 µs |
| verify: acknowledged (no read-back) | 4.3 µs | 4.2 µs | 4.4 µs |
| ledger append (hash-chained row) | 79 µs | 76 µs | 100 µs |
| **whole action: act, acknowledged** | **164 µs** | 160 µs | 231 µs |
| whole action: ask (auto-approved), acknowledged | 195 µs | 185 µs | 302 µs |
| whole action: act + custom `verify=` | 181 µs | 172 µs | 291 µs |
| whole action: ask + read-back verified (fake vendor) | 243 µs | 231 µs | 372 µs |

Read that last row carefully: **the 243 µs is Attest's work, not a real read-back.** Against a real system of
record, read-back costs one extra HTTP round trip — typically 50–300 ms, which dwarfs everything above. That is
the honest price of `verified`: roughly double the wall-clock of the write itself.

The rest is noise next to an LLM turn. A full action is about a sixth of a millisecond, dominated by the SQLite
write that makes the ledger durable.

## Chain verification

| what | mean |
| --- | --- |
| `verify_chain()` over 10,000 rows | 347 ms |
| `verify_chain(since_checkpoint=True)` over 100 rows after a checkpoint | 2.2 ms |

Verification is linear in rows, so a long ledger gets slow: a million rows is tens of seconds. Two ways to bound
it, both already in the product:

- **Checkpoints.** `attest checkpoint` signs the head; `attest verify --since-checkpoint` (or
  `verify_chain(since_checkpoint=True)`) starts there. Everything before was verified when it was signed — and
  by anyone holding the [anchor](hardening.md), if you published one.
- **Retention.** `attest prune --older-than-days 30` drops old rows behind a checkpoint; the remaining chain
  still verifies end to end.

## Choosing where to spend

| you want | do |
| --- | --- |
| lowest latency on a hot path | no read-back: the row is `acknowledged`, ~164 µs |
| proof the write landed | read-back: one extra round trip to the vendor |
| proof nobody edited the ledger | a checkpoint per day, anchored somewhere you do not control |
| a long history that still verifies fast | checkpoint + `--since-checkpoint`, prune on your retention window |
