# Hardening: anchoring, signatures, SSO, on-prem

## Checkpoints you cannot rewrite

A signed checkpoint proves the ledger head at a moment. Publishing it somewhere you do not control proves it
*later*, even against an operator with database access.

```bash
attest checkpoint                                    # HMAC (ATTEST_LEDGER_KEY) or Ed25519 (pip install "attest[signing]")
attest anchor --git ~/audit-anchors                  # commit {scope, seq, hash, signed_at} into a git repo
attest anchor --file /mnt/worm/attest-anchors.jsonl  # append-only file (WORM bucket, shared drive)
attest anchor --url https://anchor.example/v1 --verify   # HTTP transparency / timestamping service
```

`FileAnchor`, `GitAnchor`, `HttpAnchor` implement `publish(cp)` and `lookup(cp)`; `verify_anchor()` checks the
anchored `(scope, seq, hash)` matches. Ed25519 (`attest.ledger.signing`) gives public-key signatures anyone can
verify offline; HMAC stays the zero-dependency default.

## SSO (OIDC)

Set `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI`, `ATTEST_SESSION_SECRET` on the
cloud. `GET /auth/login` → provider → `/auth/callback` sets a signed session cookie that acts as an **approver**
for the org whose `domain` / `sso_domains` matches the email; emails in `sso_admins` become admins
(`sso_default_role` changes the default). Works with Okta, Entra, Google, Auth0, Keycloak; SAML IdPs through
their OIDC bridge.

## On-prem

`deploy/on-prem/docker-compose.yml`: API + dashboard on one host, SQLite on a volume, no external services.
See `deploy/on-prem/README.md`. The SDK itself is offline-first (SQLite ledger, YAML policy, console gate)
and syncs through an outbox when a cloud is reachable.

## SOC 2 readiness

See the [checklist](soc2.md): what Attest provides per control area and what stays with the operator.
