# CLI

```bash
attest serve [--host 127.0.0.1] [--port 8321]      # local web inbox + API
attest ledger [--limit 20] [--run RUN] [--json]
attest verify                                      # hash chain
attest pending
attest confirm <id|token> approve|reject [--edits '{"k": "v"}'] [--approver me] [--note …]
attest export --format json|csv
attest digest [--since 24] [--json] [--slack-token … --slack-channel …]
attest checkpoint · attest anchor --git|--file|--url [--verify] · attest prune --older-than-days N
attest recipes list | propose --openapi|--mcp-tools … --system X [--llm] | install <file>
attest gateway … (= attest-gateway) · attest mcp-proxy … (= attest-mcp) · attest-mcp-server
```

Environment: `ATTEST_LEDGER`, `ATTEST_POLICY`, `ATTEST_AUTO_APPROVE`, `ATTEST_AGENT`, `ATTEST_ACTOR`,
`ATTEST_CLOUD_URL`, `ATTEST_API_KEY`, `ATTEST_SERVER_TOKEN`.
