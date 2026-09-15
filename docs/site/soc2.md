# SOC 2 readiness checklist (engineering view)

Not a certification. The controls an auditor asks about, and where Attest stands. Items marked *you* are
operator responsibilities.

| control area | Attest today | you |
| --- | --- | --- |
| Access control | API keys with roles (agent / approver / admin), hashed at rest, revocable; OIDC SSO with per-domain org mapping; approver-group enforcement on confirmations | key rotation policy, SSO enforced, admin list reviewed |
| Audit logging | every agent action is a hash-chained ledger row with decision, approver identity, outcome, verification; admin actions (policy versions, key creation) are attributable to a key | retention set; exports archived |
| Integrity | per-org hash chain, signed checkpoints (HMAC or Ed25519), external anchoring (file / git / HTTP) | daily checkpoint + anchor job |
| Data minimisation | params and results stored as hashes plus allow-listed previews; bodies never; vendor tokens never reach the cloud (pass-through read-back) | keep previews allow-list reviewed |
| Encryption | TLS terminated at your ingress; Postgres at rest per your platform | TLS certificates, disk encryption |
| Availability | stateless API, Postgres, health endpoint, rate limits, backups script | monitoring, alerting, restore drill |
| Change management | CI on every change (tests, lint, docs, dashboard build), versioned policies with author | branch protection, review |
| Vendor management | optional Stripe (billing), Slack (confirmations), Nango (read-only verify), Sentry (errors) — each configurable per org and off by default | DPAs with the ones you enable |
| Incident response | `unverified` rows surface contradictions immediately; exports for investigation | runbook, on-call |

Evidence you can hand over: `GET /v1/export?format=eu-ai-act` (signed manifest), checkpoints + anchor receipts,
policy versions (`GET /v1/policy/versions`), key list (`GET /v1/keys`).
