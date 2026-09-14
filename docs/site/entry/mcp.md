# MCP proxy — zero code

Put `attest-mcp` between any MCP client (Claude Code, Cursor, your own) and any stdio MCP server:

```json
{ "mcpServers": { "gmail": { "command": "attest-mcp",
    "args": ["--upstream", "npx -y @modelcontextprotocol/server-gmail", "--server", "gmail", "--mode", "block"] } } }
```

Every `tools/call` is normalized by tool name (`gmail_send_message` ⇒ gmail / send), decided, gated,
forwarded, verified and recorded. `tools/list` gains one tool, `attest_resume`.

| mode | behaviour |
| --- | --- |
| `block` | the call waits for a decision in the web inbox / Slack (`--timeout`, default 900 s) |
| `pending` | returns `{"status": "pending_confirmation", "resume_token"}`; the agent calls `attest_resume` once a human decided |
| `auto` | approve everything (development only) |

**Read-back:** MCP tool pairs. A server exposing `create_issue` and `get_issue` (one required id argument)
gets `create_issue` verified by fetching the issue and comparing fields — no configuration.

Options: `--policy attest.yaml`, `--ledger`, `--slack-token --slack-channel`, `--webhook`, `--inbox-url`,
`--agent`, `--actor`. Run `attest serve` alongside for the inbox. Stdio upstreams only in v0.
