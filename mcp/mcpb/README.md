# Attest — Claude Desktop / Smithery bundle

Six tools an agent can call before and after it acts: `attest_decide`, `attest_confirm`, `attest_confirm_status`,
`attest_record`, `attest_verify`, `attest_ledger`.

Requires [uv](https://docs.astral.sh/uv/) on the machine — the bundle runs `uvx attestlayer`, so it always uses
the published package and never bundles platform-specific wheels.

Configure tokens in the extension settings to turn on read-back for Gmail, Slack, HubSpot, Notion and Linear.
Everything stays local: tokens are used in-process, the ledger is a SQLite file you own.

Build it yourself:

```bash
python mcp/mcpb/build.py            # regenerates metadata, then packs both flavours
```

Two files come out: `attest-<v>.mcpb` for Claude Desktop (MCPB tool shape) and `attest-<v>-smithery.mcpb`
whose tools also carry `inputSchema`, which Smithery's validator requires and the MCPB CLI rejects.

`config-schema.json` is the JSON Schema for the settings above; Smithery takes it with `--config-schema`
because the MCPB manifest cannot carry one.
