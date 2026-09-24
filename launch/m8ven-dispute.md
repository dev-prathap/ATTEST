# M8ven Trust Index — publisher response

Listing: `https://m8ven.ai/mcp/dev-prathap/attest` · grade C, 74/100 · read at commit `31dc3fe`.

Two findings. One is a false positive with a one-line proof. One was correct and is now fixed.

---

## 1. Dispute — "Secret credentials may flow to a network call"

> 2 flows detected: `STRIPE_SECRET_KEY`, `ANTHROPIC_API_KEY`. We can't prove the destination matches
> the brand the credential belongs to.

Both destinations are string literals in the same function that reads the credential. There is no
dynamic host, no configurable base URL, and no indirection between the two.

**`STRIPE_SECRET_KEY`** — `cloud/attest_cloud/billing.py`, key read at line 183, used at line 187:

```python
req = urllib.request.Request("https://api.stripe.com/v1/" + path, data=data, method="POST",
                             headers={"Authorization": f"Bearer {key}"})
```

**`ANTHROPIC_API_KEY`** — `attest/verify/recipes/generate.py`, key read at line 115, used at line 120:

```python
req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST",
                             headers={"x-api-key": key, ...})
```

Neither reaches the MCP server. Three independent reasons:

1. **Not imported.** `attest/mcp/server.py` imports neither module. Nothing in the server's call path
   can reach either function.
2. **Not in the package.** The published `attestlayer` distribution ships `packages = ["attest"]`
   (`pyproject.toml` line 48). `attest_cloud`, which holds the Stripe code, is a separate package that
   is not installed by `pip install attestlayer` or `uvx attestlayer`. Someone running the MCP server
   does not have that file on disk.
3. **Opt-in and off by default.** The Anthropic call sits behind the `--llm` flag on the recipe
   generator CLI, and the function takes an injected `call()` in every other path. Running the MCP
   server never invokes it.

The scan appears to have attributed monorepo-wide findings to the MCP server. The repository holds an
SDK, a separate cloud service and a dashboard; only the SDK is what the listing describes.

**Requested correction:** drop both flows from the MCP server's findings, or re-scope them to the
`cloud/` package with the destination named. We would rather you keep a finding that says "this
repository contains a cloud service that calls Stripe" than remove it entirely, as long as it is not
attributed to the server someone installs.

### On the wording, which we think you got right

Your phrasing was "we can't prove the destination matches", not "this leaks credentials". That
distinction is the whole thesis of this project: a check that could not run must not be reported as a
failure, and it must not be reported as a pass either. Our own ledger calls that `acknowledged`. We
would only object if a static scanner's inability to resolve a destination were scored as evidence of
wrongdoing, and yours was not.

---

## 2. Accepted — missing tool annotations

> 6/6 tools missing one or more hints.

Correct. All six tools declared `name`, `description` and `inputSchema` and no behaviour hints, so a
host had no way to warn a user before invoking one that writes or reaches a third-party system.

Fixed. Every tool now declares all four hints as explicit booleans, matching what its handler actually
does:

| tool | readOnly | destructive | idempotent | openWorld |
| --- | --- | --- | --- | --- |
| `attest_decide` | true | false | true | false |
| `attest_confirm` | false | false | false | **true** |
| `attest_confirm_status` | true | false | true | false |
| `attest_record` | **false** | false | false | false |
| `attest_verify` | true | false | true | **true** |
| `attest_ledger` | true | false | true | false |

`attest_confirm` writes a pending request and notifies Slack or a webhook, so it is neither read-only
nor closed. `attest_record` appends a ledger row. `attest_verify` reads the third-party system of
record and writes nothing, here or there. `destructiveHint` is false everywhere because the ledger is
append-only and confirmations are superseded rather than deleted.

Two tests now enforce this, including one asserting the hints match handler behaviour, so the
annotations cannot drift.

---

## Not disputed

The grade cap at C pending adoption is your methodology and we have no quarrel with it. The credential
inventory is accurate: the server does read those environment variables, and saying so is useful.
