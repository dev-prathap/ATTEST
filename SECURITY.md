# Security policy

## Reporting a vulnerability

Use GitHub's private reporting: **[Report a vulnerability](https://github.com/dev-prathap/ATTEST/security/advisories/new)**.
It is enabled on this repository and the report stays private until a fix ships.

Please do not open a public issue for anything with a security impact.

Expect an acknowledgement within three working days, and an assessment with a fix or a rejection within
fourteen. If a fix ships, you will be credited in the advisory unless you ask otherwise.

## Supported versions

Attest is pre-1.0. Fixes land on `main` and in the next release. Only the latest published version of
`attestlayer` on PyPI and npm is supported.

## What counts as a vulnerability here

Attest exists to make a record that a third party can trust, so anything that lets the record lie is a
security issue, not just a bug. In scope:

- **Ledger forgery.** Writing, altering or deleting a ledger row so the hash chain still verifies.
- **Chain verification bypass.** Making `attest verify` report an intact chain over tampered history,
  including through checkpoints, pruning or anchoring.
- **Level inflation.** Any path that reports `verified` when the read-back did not run or did not
  compare the written fields. This is the one that matters most.
- **Policy bypass.** Getting an action past a gate that policy said required approval, including
  through descriptor normalisation, verb classification, or the resume path after a confirmation.
- **Confirmation forgery.** Approving on someone else's behalf, replaying a resume token, or altering
  the parameters between approval and execution without the edit being recorded.
- **Credential exposure.** Vendor tokens, API keys or raw parameters reaching the cloud, the ledger, a
  log line or an export. Read-back is meant to run in the caller's process with the caller's own
  credentials; anything that breaks that boundary is in scope.
- **Cloud tenancy.** Reading or writing another organisation's ledger, policy, keys or confirm inbox.

Out of scope: the behaviour of your own tool, the third-party API's own bugs, and denial of service
against a self-hosted deployment you control. Reports generated solely by an automated scanner with no
demonstrated impact will be closed.

## Handling secrets in a report

Redact tokens and customer data before sending. A ledger row with hashes and field names is almost
always enough to reproduce a verification issue, and raw parameters are never needed.
