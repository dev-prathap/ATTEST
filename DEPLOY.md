# Deploying Attest — the runbook

Brand **Attest**. Packages: PyPI **`attestlayer`** (import `attest`, CLI `attest`, `attest-mcp`, `attest-mcp-server`,
`attest-gateway`), npm **`attestlayer`**, images **`ghcr.io/dev-prathap/attest-api`** and **`attest-dashboard`**,
docs at **https://dev-prathap.github.io/ATTEST/**. Everything ships from one git tag.

## 0. One-time accounts (you)

| what | where | why |
| --- | --- | --- |
| PyPI — **either** a pending publisher **or** a token | see below | publishes the Python SDK |
| GitHub environment `pypi` | repo → Settings → Environments → New: `pypi` | required by the trusted publisher path |
| npm org `attestlayer` | npmjs.com → create org `attestlayer` (free, public) → Access token (Automation) | `attestlayer` |
| GitHub secret `NPM_TOKEN` | repo → Settings → Secrets → Actions | npm publish with provenance |
| GitHub Pages | repo → Settings → Pages → Source: **GitHub Actions** | docs site |
| Domain `attestlayer.dev` (or .io/.ai) | any registrar | `app.` dashboard, `api.` cloud, `docs.` (CNAME to Pages, optional) |

### PyPI: pick one path

**a. Trusted publishing (recommended — no token anywhere).** The project does not exist on PyPI yet, so add a
*pending* publisher: pypi.org → **Publishing** (left sidebar) → "Add a new pending publisher":

| field | value |
| --- | --- |
| PyPI Project Name | `attestlayer` |
| Owner | `dev-prathap` |
| Repository name | `ATTEST` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

Then create the `pypi` environment in the repo (Settings → Environments → New environment). Nothing else.

**b. API token.** pypi.org → Account settings → Add API token (scope: entire account, until the project exists)
→ `gh secret set PYPI_API_TOKEN --repo dev-prathap/ATTEST`. The workflow uses the secret when it is present and
falls back to trusted publishing when it is not. After the first release, replace it with a project-scoped token
or switch to path (a) and delete the secret.

## 1. Release the SDKs, MCP server and images

```bash
git tag v0.1.0 && git push --tags        # release.yml: tests → PyPI → npm → GHCR images → GitHub release
```

After the workflow is green:

```bash
pip install attestlayer                   # Python SDK + CLI + attest-mcp + attest-mcp-server + attest-gateway
npm install attestlayer              # TypeScript SDK
uvx --from attestlayer attest-mcp-server  # run the MCP server without installing anything
```

Bump `version` in `pyproject.toml` and `packages/attest-ts/package.json` before the next tag.

## 2. MCP server / proxy for Claude Code, Cursor, any MCP client

Users add to their MCP config (no server to host — it runs on their machine with their tokens):

```json
{ "mcpServers": {
    "attest": { "command": "uvx", "args": ["--from", "attestlayer", "attest-mcp-server"],
                "env": { "ATTEST_POLICY": "attest.yaml", "GMAIL_TOKEN": "…", "HUBSPOT_TOKEN": "…" } },
    "gmail":  { "command": "uvx", "args": ["--from", "attestlayer", "attest-mcp",
                "--upstream", "npx -y @modelcontextprotocol/server-gmail", "--server", "gmail", "--mode", "block"] } } }
```

Approvals for `--mode block` come from `attest serve` (local inbox) or Attest Cloud; `--mode pending` returns a
resume token. Ship the `skills/verified-actions/SKILL.md` to skills marketplaces so coding agents know the tools.

## 2b. MCP registries (after the PyPI release)

Listing files live in `mcp/`; the README carries the `mcp-name:` ownership markers the registry checks on PyPI.

```bash
brew install mcp-publisher                       # or the curl one-liner in the registry quickstart
mcp-publisher login github                       # namespace io.github.dev-prathap/*
mcp-publisher validate mcp/server.json && mcp-publisher publish mcp/server.json          # io.github.dev-prathap/attest
mcp-publisher validate mcp/server-proxy.json && mcp-publisher publish mcp/server-proxy.json   # …/attest-proxy
```
Bump `version` in both files with each release (tests assert they match `pyproject.toml`).

**Claude Desktop / Smithery (MCPB bundle):** the release workflow builds `attest-<version>.mcpb` from
`mcp/mcpb/` and attaches it to the GitHub release. To list it on Smithery:

Each release carries two bundles, because the two validators disagree about the tool shape:

| file | for | tools carry |
| --- | --- | --- |
| `attest-<v>.mcpb` | Claude Desktop, the MCPB spec | `name`, `description` |
| `attest-<v>-smithery.mcpb` | Smithery | `name`, `description`, `inputSchema` |

```bash
gh release download v0.1.0 --repo dev-prathap/ATTEST --pattern '*.mcpb' --clobber
npx -y @smithery/cli mcp publish ./attest-0.1.0-smithery.mcpb -n <your-namespace>/attest
```

The namespace must already exist on smithery.ai (your username, or an org you created there).
Build locally with `python mcp/mcpb/build.py`.

The bundle runs `uvx attestlayer`, so it needs `uv` on the user's machine and never ships platform-specific
wheels. Users who prefer no bundle can add the registry entry instead.

**Glama:** `glama.json` at the repo root lists the maintainer; claim the server at glama.ai/mcp after the repo is
indexed. **Cursor / other directories:** point at the MCP Registry entry.

## 3. Attest Cloud (API + dashboard)

**Option A — one VPS, one command** (Hetzner / DigitalOcean / Lightsail, ~$6/mo). Point `api.` and `app.`
A records at the host first, then:

```bash
curl -fsSL https://raw.githubusercontent.com/dev-prathap/ATTEST/main/deploy/bootstrap.sh | \
  ATTEST_DOMAIN=attestlayer.dev ATTEST_ACME_EMAIL=you@example.com bash
```

It installs Docker, clones the repo to `/opt/attest`, generates secrets into `deploy/.env`, starts Postgres +
API + dashboard behind Caddy (automatic TLS), and installs cron jobs for the nightly `pg_dump` and the daily
ledger checkpoint. It then prints the `curl` that creates your first org.

Manual equivalent: `cp .env.example .env` then
`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`.

**Option B — Fly.io**: `cd deploy && fly launch --copy-config` (sample `fly.toml`), `fly postgres create`,
`fly secrets set DATABASE_URL=… ATTEST_CLOUD_BOOTSTRAP_TOKEN=… ATTEST_SIGNING_KEY=…`, `fly deploy`.
Dashboard: deploy `dashboard/` to Vercel (`NEXT_PUBLIC_ATTEST_CLOUD_URL=https://api.attestlayer.dev`).

**Option C — on-prem for a customer**: `deploy/on-prem/docker-compose.yml` (SQLite, no external services).

Env vars the API reads:

| var | purpose |
| --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://…` (SQLite for dev) |
| `ATTEST_CLOUD_BOOTSTRAP_TOKEN` | required to create orgs and to set plans |
| `ATTEST_SIGNING_KEY` | HMAC key for checkpoints and export manifests |
| `ATTEST_CORS_ORIGINS` | dashboard origin(s) |
| `ATTEST_RATE_LIMIT` / `ATTEST_RATE_BURST` | per-key rate limit |
| `SLACK_SIGNING_SECRET` | global fallback for Slack interactivity (orgs can set their own) |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_TEAM`, `STRIPE_PRICE_PRO` | billing |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI`, `ATTEST_SESSION_SECRET`, `ATTEST_DASHBOARD_URL` | SSO |
| `SENTRY_DSN` | error tracking (optional) |

**First org**:
```bash
curl -X POST https://api.attestlayer.dev/v1/orgs -H "X-Bootstrap-Token: $ATTEST_CLOUD_BOOTSTRAP_TOKEN" \
     -H "Content-Type: application/json" -d '{"name": "Acme", "domain": "acme.com"}'      # → admin api_key (shown once)
```
Open the dashboard → Settings → paste the key → create an `agent` key for SDKs and `approver` keys for people
(or turn on SSO). Slack: create an app (bot scopes `chat:write`, interactivity URL `https://api.attestlayer.dev/slack/interact`),
put the bot token + signing secret + channel in org settings. Stripe: create Team / Pro prices, set the price ids,
webhook `https://api.attestlayer.dev/stripe/webhook` for `checkout.session.completed`, `customer.subscription.*`, `invoice.*`.

## 4. Docs site

Pushes to `main` that touch `docs/site/` publish to GitHub Pages (`docs.yml`). Custom domain: add `docs.attestlayer.dev`
CNAME in Settings → Pages and set `site_url` in `mkdocs.yml`.

## 5. Smoke test after a release

```bash
pip install attestlayer && attest --help && attest-mcp-server < /dev/null
python -c "import attest; print(attest.__version__)"
npx -y -p attestlayer node -e "import('attestlayer').then(m => console.log(Object.keys(m).length, 'exports'))"
curl https://api.attestlayer.dev/healthz
```

## Checklist before v0.1.0

- [ ] PyPI trusted publisher + `pypi` environment · [ ] npm org + `NPM_TOKEN` · [ ] Pages enabled
- [ ] domain registered; `api.` / `app.` / `docs.` DNS
- [ ] cloud host chosen; `.env` filled; TLS in front; backups cron; checkpoint + anchor cron
- [ ] Slack app created; Stripe prices; (optional) OIDC app; Sentry DSN
- [ ] `git tag v0.1.0 && git push --tags`, then the smoke test above
