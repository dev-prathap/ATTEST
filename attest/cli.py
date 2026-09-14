"""`attest` command line: serve the inbox, inspect the ledger, decide pending requests.

    attest serve [--port 8321]
    attest ledger [--limit 20] [--run RUN] [--json]
    attest verify
    attest pending
    attest confirm <id|token> approve|reject [--edits '{"k": "v"}'] [--approver me] [--note …]
    attest export --format json|csv
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from attest.gate import ConfirmDecision
from attest.gate.store import PendingStore
from attest.ledger import SqliteLedger


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="attest", description="Proof layer for AI agents")
    ap.add_argument("--ledger", default=os.environ.get("ATTEST_LEDGER", ".attest/ledger.sqlite"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the local confirm inbox + API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8321)

    lg = sub.add_parser("ledger", help="list ledger entries")
    lg.add_argument("--limit", type=int, default=20)
    lg.add_argument("--run")
    lg.add_argument("--json", action="store_true")

    sub.add_parser("verify", help="verify the hash chain")
    sub.add_parser("pending", help="list pending confirm requests")

    c = sub.add_parser("confirm", help="decide a pending request")
    c.add_argument("request")
    c.add_argument("decision", choices=["approve", "reject", "approved", "rejected"])
    c.add_argument("--edits")
    c.add_argument("--approver", default=os.environ.get("USER", "cli"))
    c.add_argument("--note")

    e = sub.add_parser("export", help="export the ledger")
    e.add_argument("--format", choices=["json", "csv"], default="json")

    a = ap.parse_args(argv)
    if a.cmd == "serve":
        from attest.server import AttestServer
        srv = AttestServer(PendingStore(a.ledger), SqliteLedger(a.ledger), host=a.host, port=a.port)
        print(f"attest inbox at {srv.url}  (ledger {a.ledger})", file=sys.stderr)
        srv.serve_forever()
        return 0
    ledger = SqliteLedger(a.ledger)
    if a.cmd == "ledger":
        rows = ledger.entries(run_id=a.run, limit=a.limit, newest_first=True)
        if a.json:
            print(json.dumps([{**r.payload(), "seq": r.seq, "hash": r.hash} for r in rows], indent=2, default=str))
        else:
            for r in rows:
                d = r.descriptor
                target = str(d.get("target") or "-")[:32]
                print(f"#{r.seq:<5} {r.created_at:%Y-%m-%d %H:%M:%S} {d['system']}.{d['verb']:<8} → {target:<32} "
                      f"{r.decision:<8} {r.confirm.status:<12} {r.verification.level:<15} {r.hash[:12]}")
        return 0
    if a.cmd == "verify":
        rep = ledger.verify_chain()
        detail = f" broken_at={rep.broken_at} {rep.problems}" if not rep.ok else ""
        print(f"chain ok={rep.ok} entries={rep.checked}{detail}")
        return 0 if rep.ok else 1
    if a.cmd == "export":
        print(ledger.export(a.format))
        return 0
    store = PendingStore(a.ledger)
    if a.cmd == "pending":
        for row in store.pending():
            d = row["descriptor"]
            print(f"{row['id']}  {d['system']}.{d['verb']} → {d.get('target') or '-'}  risk={row['risk_tier']}  "
                  f"{row['requested_at']}  token={row['resume_token']}")
        return 0
    if a.cmd == "confirm":
        status = {"approve": "approved", "reject": "rejected"}.get(a.decision, a.decision)
        edits = json.loads(a.edits) if a.edits else None
        if edits and status == "approved":
            status = "edited"
        ok = store.decide(a.request, ConfirmDecision(status, a.approver, edits, a.note, channel="cli"))
        print("recorded" if ok else "not pending (unknown or already decided)")
        return 0 if ok else 1
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
