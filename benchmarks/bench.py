"""What Attest costs per action.

    python benchmarks/bench.py                 # table
    python benchmarks/bench.py --json out.json # machine-readable

Measures the overhead Attest adds, with the customer's own work stubbed out, so the numbers are the layer and
nothing else. Read-back is measured against an in-process fake so the figure is Attest's work, not the vendor's
latency — a real read-back costs one extra HTTP round trip to the system of record, which dominates.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from attest import Attest, AutoGate, SqliteLedger
from attest.descriptor import ActionDescriptor
from attest.policy import PolicyEngine
from attest.registry import detect
from attest.verify import verify


def timeit(fn: Callable[[], Any], *, n: int, warmup: int = 50) -> dict[str, float]:
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(n):
        t0 = time.perf_counter_ns()
        fn()
        samples.append((time.perf_counter_ns() - t0) / 1000)        # µs
    samples.sort()
    return {"n": n, "mean_us": statistics.fmean(samples), "p50_us": samples[len(samples) // 2],
            "p95_us": samples[int(len(samples) * 0.95)], "p99_us": samples[int(len(samples) * 0.99)],
            "ops_per_sec": 1_000_000 / statistics.fmean(samples)}


class FakeGmail:
    """Shaped like googleapiclient's resource; returns instantly so the number is Attest's work."""

    def __init__(self, to: str, subject: str):
        self.data = {"id": "m1", "threadId": "t1", "labelIds": ["SENT"],
                     "payload": {"headers": [{"name": "To", "value": to}, {"name": "Subject", "value": subject}]}}

    def users(self):
        return self

    def messages(self):
        return self

    def get(self, **kw):
        return type("R", (), {"execute": lambda s: self.data})()


def suite(n: int) -> dict[str, dict[str, float]]:
    params = {"to": "arun@newco.com", "subject": "Follow-up", "body": "…" * 40}
    out: dict[str, dict[str, float]] = {}

    # 1. the pieces
    out["detect (tool name)"] = timeit(lambda: detect(tool_name="gmail_send_message"), n=n)
    out["detect (method + url)"] = timeit(lambda: detect(method="POST", url="https://api.hubapi.com/crm/v3/objects/deals"), n=n)
    engine = PolicyEngine()
    d = ActionDescriptor(system="gmail", verb="send", target=params["to"], params=params, actor="ram@acme.com")
    out["policy evaluate"] = timeit(lambda: engine.evaluate(d), n=n)
    out["verify: acknowledged"] = timeit(lambda: verify(d, {"id": "m1"}), n=n)

    ledger = SqliteLedger(":memory:")
    from attest.ledger import LedgerEntry
    out["ledger append (hash chain)"] = timeit(
        lambda: ledger.append(LedgerEntry.from_descriptor(d, decision="act", risk_tier="high")), n=n)

    # 2. end to end, the customer's tool stubbed to nothing
    def client(**kw) -> Attest:
        return Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), actor="ram@acme.com", agent="bench", **kw)

    at = client()
    act = at.action(system="hubspot", verb="update", target="deal_id")(lambda deal_id, dealname: {"id": deal_id})
    out["action: act, acknowledged"] = timeit(lambda: act("777", "Acme"), n=n)

    at_ask = client()
    ask = at_ask.action(system="gmail", verb="send", target="to")(lambda to, subject, body: {"id": "m1"})
    out["action: ask (auto-approved), acknowledged"] = timeit(lambda: ask(**params), n=n)

    at_v = client(readers={"gmail": FakeGmail(params["to"], params["subject"])})
    verified = at_v.action(system="gmail", verb="send", target="to")(lambda to, subject, body: {"id": "m1"})
    out["action: ask + read-back verified (fake vendor)"] = timeit(lambda: verified(**params), n=n)

    at_c = client()
    custom = at_c.action(system="x", verb="update", verify=lambda r: r["ok"])(lambda a: {"ok": True})
    out["action: act + custom verify"] = timeit(lambda: custom(1), n=n)

    # 3. chain verification over a filled ledger
    big = SqliteLedger(":memory:")
    for _ in range(10_000):
        big.append(LedgerEntry.from_descriptor(d, decision="act", risk_tier="high"))
    rep = timeit(big.verify_chain, n=max(5, n // 400), warmup=2)
    rep["rows"] = 10_000
    out["verify_chain (10k rows, from genesis)"] = rep
    big.checkpoint()
    for _ in range(100):
        big.append(LedgerEntry.from_descriptor(d, decision="act", risk_tier="high"))
    rep = timeit(lambda: big.verify_chain(since_checkpoint=True), n=max(20, n // 40), warmup=5)
    rep["rows"] = 100
    out["verify_chain (100 rows since checkpoint)"] = rep
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=2000, help="samples per measurement")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args()

    import platform
    import sys
    results = suite(a.n)
    env = {"python": platform.python_version(), "platform": platform.platform(), "machine": platform.machine(),
           "implementation": sys.implementation.name}

    width = max(len(k) for k in results)
    print(f"{'measurement':<{width}}  {'mean':>9}  {'p50':>9}  {'p95':>9}  {'ops/s':>10}")
    print("-" * (width + 45))
    for name, r in results.items():
        unit = lambda v: f"{v / 1000:.2f} ms" if v >= 1000 else f"{v:.1f} µs"   # noqa: E731
        print(f"{name:<{width}}  {unit(r['mean_us']):>9}  {unit(r['p50_us']):>9}  {unit(r['p95_us']):>9}  "
              f"{r['ops_per_sec']:>10,.0f}")
    print(f"\n{env['python']} · {env['machine']} · {env['platform']}")
    print("The customer's own tool call is stubbed out: these are Attest's costs, not the vendor's latency.")

    if a.json_out:
        Path(a.json_out).write_text(json.dumps({"env": env, "samples": a.n, "results": results}, indent=2))
        print(f"wrote {a.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
