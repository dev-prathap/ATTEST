# Attest — Claude Desktop / Smithery bundle

Six tools an agent can call before and after it acts: `attest_decide`, `attest_confirm`, `attest_confirm_status`,
`attest_record`, `attest_verify`, `attest_ledger`.

Requires [uv](https://docs.astral.sh/uv/) on the machine — the bundle runs `uvx attestlayer`, so it always uses
the published package and never bundles platform-specific wheels.

Configure tokens in the extension settings to turn on read-back for Gmail, Slack, HubSpot, Notion and Linear.
Everything stays local: tokens are used in-process, the ledger is a SQLite file you own.

Build it yourself:

```bash
python mcp/mcpb/sync_tools.py                       # tools + config-schema.json from the real server
npx @anthropic-ai/mcpb pack mcp/mcpb attest.mcpb
```

`config-schema.json` is the JSON Schema for the settings above; Smithery takes it with `--config-schema`
because the MCPB manifest cannot carry one.
