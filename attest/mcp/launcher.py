"""`attestlayer` — the single entry point registries run with `uvx attestlayer`.

    uvx attestlayer                      → the Attest MCP server (attest_decide / confirm / record / verify / ledger)
    uvx attestlayer server               → same
    uvx attestlayer proxy --upstream "npx -y @modelcontextprotocol/server-gmail" --server gmail   → the MCP proxy
    uvx attestlayer gateway --port 8322  → the HTTP gateway
    uvx attestlayer serve                → the local confirm inbox
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else list(argv)
    cmd = args[0] if args and not args[0].startswith("-") else "server"
    rest = args[1:] if args and not args[0].startswith("-") else args
    if cmd == "server":
        from attest.mcp.server import main as server_main
        server_main()
    elif cmd == "proxy":
        from attest.mcp.proxy import main as proxy_main
        proxy_main(rest)
    elif cmd == "gateway":
        from attest.gateway.server import main as gw_main
        gw_main(rest)
    elif cmd == "serve":
        from attest.cli import main as cli_main
        sys.exit(cli_main(["serve", *rest]))
    elif cmd in ("-h", "--help", "help"):
        print(__doc__)
    else:
        print(f"attestlayer: unknown command {cmd!r}\n{__doc__}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":  # pragma: no cover
    main()
