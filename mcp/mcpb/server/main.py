"""MCPB entry point. Claude Desktop launches `uvx attestlayer`; this file is the declared entry point and also
works when the bundle is run directly with `python server/main.py` against an installed `attestlayer`."""
from attest.mcp.server import main

if __name__ == "__main__":
    main()
