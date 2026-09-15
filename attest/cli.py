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
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] in ("gateway", "mcp-proxy"):  # single binary: pass the rest through untouched
        if argv[0] == "gateway":
            from attest.gateway.server import main as gw_main
            gw_main(argv[1:])
        else:
            from attest.mcp.proxy import main as mcp_main
            mcp_main(argv[1:])
        return 0
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
    dg = sub.add_parser("digest", help="agent-activity digest with anomaly flags")
    dg.add_argument("--since", type=float, default=24, help="hours")
    dg.add_argument("--json", action="store_true")
    dg.add_argument("--slack-token")
    dg.add_argument("--slack-channel")
    sub.add_parser("pending", help="list pending confirm requests")

    c = sub.add_parser("confirm", help="decide a pending request")
    c.add_argument("request")
    c.add_argument("decision", choices=["approve", "reject", "approved", "rejected"])
    c.add_argument("--edits")
    c.add_argument("--approver", default=os.environ.get("USER", "cli"))
    c.add_argument("--note")

    rc = sub.add_parser("recipes", help="list / propose / install read-back recipes")
    rcs = rc.add_subparsers(dest="rcmd", required=True)
    rcs.add_parser("list")
    rp = rcs.add_parser("propose", help="derive recipe proposals from an OpenAPI spec or an MCP tools list")
    rp.add_argument("--openapi")
    rp.add_argument("--mcp-tools", help="JSON file with the tools/list result (or a tools array)")
    rp.add_argument("--system", required=True)
    rp.add_argument("--llm", action="store_true", help="refine compare fields with a model (ANTHROPIC_API_KEY)")
    rp.add_argument("--docs", help="API docs excerpt file for the model")
    rp.add_argument("--out", default="recipes/proposals")
    ri = rcs.add_parser("install", help="copy a reviewed proposal into the recipes directory")
    ri.add_argument("file")
    ri.add_argument("--dir", default=os.environ.get("ATTEST_RECIPES_DIR") or str(__import__("pathlib").Path.home() / ".attest" / "recipes"))

    e = sub.add_parser("export", help="export the ledger")
    e.add_argument("--format", choices=["json", "csv", "ietf", "eu-ai-act"], default="json")

    sub.add_parser("checkpoint", help="sign the current ledger head (ATTEST_LEDGER_KEY)")
    an = sub.add_parser("anchor", help="publish the newest checkpoint to an external anchor")
    an.add_argument("--file", help="append-only anchor log path")
    an.add_argument("--url", help="HTTP anchor endpoint")
    an.add_argument("--git", help="git repository to commit the anchor into")
    an.add_argument("--verify", action="store_true", help="check the newest checkpoint is anchored instead of publishing")
    gw = sub.add_parser("gateway", help="run the outbound HTTP gateway (same as attest-gateway)", add_help=False)
    gw.add_argument("rest", nargs=argparse.REMAINDER)
    mp = sub.add_parser("mcp-proxy", help="run the MCP proxy (same as attest-mcp)", add_help=False)
    mp.add_argument("rest", nargs=argparse.REMAINDER)
    pr = sub.add_parser("prune", help="retention: drop old rows, keeping a checkpoint so the chain still verifies")
    pr.add_argument("--older-than-days", type=int, required=True)

    a = ap.parse_args(argv)
    if a.cmd == "serve":
        from attest.server import AttestServer
        srv = AttestServer(PendingStore(a.ledger), SqliteLedger(a.ledger), host=a.host, port=a.port)
        print(f"attest inbox at {srv.url}  (ledger {a.ledger})", file=sys.stderr)
        srv.serve_forever()
        return 0
    if a.cmd == "recipes":
        return _recipes(a)
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
    if a.cmd == "digest":
        from attest.digest import digest, render_text, slack_blocks
        d = digest(ledger.entries(), since_hours=a.since)
        print(json.dumps(d, indent=2, default=str) if a.json else render_text(d))
        if a.slack_token and a.slack_channel:
            from attest.gate.slack import _TokenClient
            _TokenClient(a.slack_token).chat_postMessage(channel=a.slack_channel, text="Attest daily digest", blocks=slack_blocks(d))
        return 0
    if a.cmd == "verify":
        rep = ledger.verify_chain()
        detail = f" broken_at={rep.broken_at} {rep.problems}" if not rep.ok else ""
        print(f"chain ok={rep.ok} entries={rep.checked}{detail}")
        return 0 if rep.ok else 1
    if a.cmd == "export":
        print(ledger.export(a.format))
        return 0
    if a.cmd == "checkpoint":
        cp = ledger.checkpoint()
        print(json.dumps(cp.to_dict()) if cp else "empty ledger")
        return 0
    if a.cmd == "anchor":
        from attest.ledger import anchor as an_mod
        cps = ledger.checkpoints()
        if not cps:
            print("no checkpoint yet — run `attest checkpoint` first")
            return 1
        cp = cps[-1]
        anchor = an_mod.FileAnchor(a.file) if a.file else an_mod.HttpAnchor(a.url, api_key=os.environ.get("ATTEST_ANCHOR_KEY")) \
            if a.url else an_mod.GitAnchor(a.git) if a.git else None
        if anchor is None:
            print("anchor needs --file, --url or --git")
            return 2
        if a.verify:
            ok = an_mod.verify_anchor(anchor, cp)
            print(f"checkpoint seq={cp.seq} hash={cp.hash[:12]}… anchored={ok}")
            return 0 if ok else 1
        r = anchor.publish(cp)
        print(json.dumps(r.to_dict()))
        return 0
    if a.cmd == "prune":
        n = ledger.prune(older_than_days=a.older_than_days)
        rep = ledger.verify_chain()
        print(f"pruned {n} row(s); chain ok={rep.ok} entries={rep.checked}")
        return 0 if rep.ok else 1
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


def _recipes(a: argparse.Namespace) -> int:
    from pathlib import Path

    from attest.verify import recipes
    from attest.verify.recipes import generate
    if a.rcmd == "list":
        for r in recipes.all_recipes():
            print(f"{r.name:<32} {r.system:<12} {','.join(r.verbs):<24} {r.source}")
        return 0
    if a.rcmd == "propose":
        if a.openapi:
            props = generate.from_openapi(a.openapi, a.system)
        elif a.mcp_tools:
            data = json.loads(Path(a.mcp_tools).read_text())
            tools = data.get("tools") if isinstance(data, dict) else data
            props = generate.from_mcp_tools(tools, a.system)
        else:
            print("propose needs --openapi or --mcp-tools", file=sys.stderr)
            return 2
        if a.llm:
            docs = Path(a.docs).read_text() if a.docs else None
            props = generate.refine_with_llm(props, docs=docs)
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{a.system}.json"
        path.write_text(json.dumps(props, indent=1))
        print(f"{len(props)} proposal(s) written to {path} — review `compare.fields`, then: attest recipes install {path}")
        return 0
    if a.rcmd == "install":
        src = Path(a.file)
        dest = Path(a.dir)
        dest.mkdir(parents=True, exist_ok=True)
        specs = json.loads(src.read_text())
        for spec in specs if isinstance(specs, list) else [specs]:
            spec["source"] = spec.get("source", "community").replace("openapi", "reviewed").replace("mcp", "reviewed")
        (dest / src.name).write_text(json.dumps(specs, indent=1))
        print(f"installed {len(specs) if isinstance(specs, list) else 1} recipe(s) into {dest / src.name}")
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
