# HTTP gateway — zero code for any HTTP client

Point the base URL at the gateway; every write is decided, gated, forwarded with your own headers, read back with
the same credentials, and recorded. Works for Nango, Composio, Arcade, `requests`, `fetch`, curl.

```bash
attest gateway --port 8322 --mode block --policy attest.yaml         # or attest-gateway …
```

```python
requests.post("http://127.0.0.1:8322/https://api.hubapi.com/crm/v3/objects/deals",        # URL in the path …
              headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}"}, json={"properties": {...}})
requests.patch("http://127.0.0.1:8322/crm/v3/objects/deals/123",                          # … or a relative path
               headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "X-Attest-Upstream": "https://api.hubapi.com"}, json=…)
```

Responses carry `X-Attest-Level`, `X-Attest-Decision`, `X-Attest-Seq`. Reads pass straight through
(`--record-reads` to log them). Refusals and rejections answer `403` before the upstream is called.

| mode | behaviour |
| --- | --- |
| `block` | waits for a human in the inbox / Slack (`--timeout`) |
| `pending` | `202 {"status": "pending_confirmation", "resume_token"}`; `POST /_attest/resume/<token>` after approval replays the original request |
| `auto` | approve everything (dev) |

Read-back: known hosts (Gmail, Slack, HubSpot, Notion, Linear, Graph …) use their reviewed recipe with your
bearer token; anything else uses the convention driver (`GET <url>/<returned id>`) or `--openapi spec` for
spec-derived paths. Headers `X-Attest-Agent`, `X-Attest-Actor`, `X-Attest-Run` label the ledger row.
Control: `GET /_attest/healthz`, `GET /_attest/ledger`.
