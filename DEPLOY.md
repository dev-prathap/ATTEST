# Deploying Attest — the runbook

Brand **Attest**. Packages: PyPI **`attestlayer`** (import `attest`, CLI `attest`, `attest-mcp`, `attest-mcp-server`,
`attest-gateway`), npm **`attestlayer`**, images **`ghcr.io/dev-prathap/attest-api`** and **`attest-dashboard`**,
docs at **https://dev-prathap.github.io/ATTEST/**. Everything ships from one git tag.

## 0. One-time accounts (you)

| what | where | why |
| --- | --- | --- |
| PyPI project `attestlayer` | pypi.org → Your projects → *Publishing* → add **trusted publisher**: owner `dev-prathap`, repo `ATTEST`, workflow `release.yml`, environment `pypi` | no API token to leak; the release workflow publishes via OIDC |
| GitHub environment `pypi` | repo → Settings → Environments → New: `pypi` | required by the trusted publisher |
| npm org `attestlayer` | npmjs.com → create org `attestlayer` (free, public) → Access token (Automation) | `attestlayer` |
| GitHub secret `NPM_TOKEN` | repo → Settings → Secrets → Actions | npm publish with provenance |
| GitHub Pages | repo → Settings → Pages → Source: **GitHub Actions** | docs site |
| Domain `attestlayer.dev` (or .io/.ai) | any registrar | `app.` dashboard, `api.` cloud, `docs.` (CNAME to Pages, optional) |

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

**Claude Desktop / Smithery (MCPB bundle):** `npx @anthropic-ai/mcpb pack mcp/mcpb attest.mcpb` → attach the
bundle to the GitHub release (`softprops/action-gh-release` already publishes release assets; add the file) and
`smithery mcp publish ./attest.mcpb -n attestlayer/attest`.

**Glama:** `glama.json` at the repo root lists the maintainer; claim the server at glama.ai/mcp after the repo is
indexed. **Cursor / other directories:** point at the MCP Registry entry.

## 3. Attest Cloud (API + dashboard)

**Option A — one VPS with Docker Compose** (simplest; Hetzner / DigitalOcean / Lightsail):

```bash
git clone https://github.com/dev-prathap/ATTEST && cd ATTEST/deploy
cp .env.example .env    # PG_PASSWORD, ATTEST_CLOUD_BOOTSTRAP_TOKEN, ATTEST_CORS_ORIGINS=https://app.attestlayer.dev
docker compose up -d    # Postgres 16 + API :8400 + dashboard :3400
```
Put Caddy / nginx in front with TLS: `api.attestlayer.dev → :8400`, `app.attestlayer.dev → :3400`.
Nightly: `deploy/backup.sh /backups` (cron) and a checkpoint + anchor job:
`curl -X POST api…/v1/ledger/checkpoint -H "Authorization: Bearer $ADMIN_KEY"`.

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
