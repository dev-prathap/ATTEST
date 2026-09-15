# Attest on-prem

Everything runs on your host; nothing leaves it. The SDK never sent vendor tokens to Attest anyway; on-prem also
keeps the ledger, confirm inbox, and policies inside your network.

```bash
cd deploy/on-prem && docker compose up -d
curl -X POST localhost:8400/v1/orgs -H "X-Bootstrap-Token: $ATTEST_CLOUD_BOOTSTRAP_TOKEN" \
     -H "Content-Type: application/json" -d '{"name": "Acme", "domain": "acme.com"}'
```

- **Storage**: SQLite on the `attest-data` volume (swap `DATABASE_URL` for Postgres at scale).
- **Backups**: `deploy/backup.sh` for Postgres; for SQLite, snapshot the volume (the ledger is append-only).
- **Integrity**: set `ATTEST_SIGNING_KEY`; run `POST /v1/ledger/checkpoint` daily and anchor the checkpoint
  externally (`attest anchor --git <repo>` or `--url` to a timestamping service).
- **SSO**: set the `OIDC_*` variables; users from `org.domain` / `sso_domains` sign in as approvers, listed
  `sso_admins` as admins.
- **Air-gapped agents**: the SDK works fully offline (SQLite ledger, YAML policy, console gate) and syncs when
  the cloud is reachable (outbox).
