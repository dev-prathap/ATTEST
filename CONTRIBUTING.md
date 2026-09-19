# Contributing to Attest

Thanks for looking. Attest is a proof layer, so the bar for a change is slightly unusual: a patch must
never make the ledger claim more than was actually checked. Everything below follows from that.

## The one rule

**A check that could not run is not a pass.** If a verifier lacks credentials, hits a read-only scope,
or meets a verb it does not understand, the row degrades to `acknowledged`. Only an actual
contradiction between the claim and the system of record earns `unverified`. A patch that turns a
missing check into `verified` will be rejected even if every test passes.

Existence alone is also not verification. Reading back an object and finding it present, without
comparing the fields that were written, is `acknowledged`.

## Set up

```bash
uv venv -p 3.12 && uv pip install -e ".[dev]" -e "./cloud[dev]"
pytest -q && (cd cloud && pytest -q)
```

TypeScript SDK:

```bash
cd packages/attest-ts && npm install && npm test
```

Dashboard:

```bash
cd dashboard && npm install && npm run dev      # :3400
```

The TypeScript and Python SDKs must produce byte-identical canonical JSON and hashes. Shared fixtures
enforce it, so a change to canonicalisation or hashing in one language needs the matching change in the
other, in the same pull request.

## Good first contribution: a read-back recipe

A recipe teaches Attest how to confirm a write in one more app. It needs nothing but that app's read
API, no architecture knowledge, and each one is independently useful.

1. Look at an existing recipe and at `attest recipes list`.
2. Add yours: the verb it covers, the read call, and the fields to compare.
3. Add a test with a fake client that returns a matching read and a mismatching read. Assert `verified`
   for the first and `unverified` for the second.
4. If the app's read API cannot confirm the write, say so in the recipe and let it return
   `acknowledged`. That is a correct outcome, not a failure.

Issues labelled `good first issue` are mostly recipes.

## Live tests

`tests/live/` runs against real Gmail, Slack, HubSpot, Notion and Linear. They need real credentials
and are skipped without them. Never commit a token, and never add a live test that writes to a shared
or production workspace.

## Pull requests

- One concern per pull request.
- Tests for anything that changes a verification outcome, a policy decision, or a ledger field.
- `pytest -q` and `(cd cloud && pytest -q)` green, plus `npm test` if you touched the TypeScript SDK.
- Describe what the change does to the ledger. If a row's level can change because of your patch, say
  which rows and why.
- Commit messages: a short imperative subject, then a body explaining why. No co-authorship trailers.

## Reporting bugs

Open an issue with the ledger row involved, redacted as needed, and what you expected its level to be.
For anything with a security impact, follow [SECURITY.md](./SECURITY.md) instead of opening an issue.

## Licence

By contributing you agree your work is licensed under the [MIT licence](./LICENSE).
