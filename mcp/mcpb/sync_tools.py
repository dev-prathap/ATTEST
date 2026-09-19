"""Keep the bundle metadata in step with the server's real tools, and emit Smithery's config schema.

    python mcp/mcpb/sync_tools.py            # rewrite manifest.json tools + config-schema.json
    python mcp/mcpb/sync_tools.py --check    # fail if either is out of date (CI)

`manifest.json` tools carry only name + description (the MCPB schema rejects anything else); the JSON Schema
for user configuration lives beside it because Smithery takes it through `--config-schema`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from attest.mcp.server import TOOLS

HERE = Path(__file__).parent
MANIFEST = HERE / "manifest.json"
CONFIG_SCHEMA = HERE / "config-schema.json"
_JSON_TYPE = {"file": "string", "directory": "string", "string": "string", "number": "number", "boolean": "boolean"}


def tools() -> list[dict]:
    return [{"name": t["name"], "description": t["description"]} for t in TOOLS]


def config_schema(user_config: dict) -> dict:
    props, required = {}, []
    for key, spec in user_config.items():
        prop = {"type": _JSON_TYPE.get(spec.get("type", "string"), "string"),
                "title": spec.get("title", key),
                "description": spec.get("description", "")}
        if spec.get("default") is not None:
            prop["default"] = spec["default"]
        if spec.get("sensitive"):
            prop["format"] = "password"
        props[key] = prop
        if spec.get("required"):
            required.append(key)
    schema = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object",
              "title": "Attest configuration", "properties": props}
    if required:
        schema["required"] = required
    return schema


def main() -> int:
    doc = json.loads(MANIFEST.read_text())
    want_tools = tools()
    want_schema = config_schema(doc.get("user_config") or {})
    have_schema = json.loads(CONFIG_SCHEMA.read_text()) if CONFIG_SCHEMA.exists() else None
    stale = doc.get("tools") != want_tools or have_schema != want_schema
    if not stale:
        return 0
    if "--check" in sys.argv:
        print("bundle metadata is stale — run: python mcp/mcpb/sync_tools.py", file=sys.stderr)
        return 1
    doc["tools"] = want_tools
    MANIFEST.write_text(json.dumps(doc, indent=2) + "\n")
    CONFIG_SCHEMA.write_text(json.dumps(want_schema, indent=2) + "\n")
    print(f"updated manifest.json ({len(want_tools)} tools) and config-schema.json ({len(want_schema['properties'])} fields)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
