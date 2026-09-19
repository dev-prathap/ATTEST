## What this changes

<!-- One or two sentences. -->

## Effect on the ledger

<!--
Required if this touches verification, policy, gates or the ledger format. Which rows can change
level, and why? If nothing changes, write "none".
-->

## Checks

- [ ] `pytest -q` and `(cd cloud && pytest -q)` pass
- [ ] `npm test` in `packages/attest-ts` passes, if the TypeScript SDK changed
- [ ] A check that cannot run still degrades to `acknowledged`, never to `verified`
- [ ] Tests cover both the matching and the contradicting read-back, if this adds a verifier
