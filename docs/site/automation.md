# Recipe automation and the open registry

Reviewed recipes cover the top systems; the long tail comes from **declarative recipes** — JSON a human can
review and the community can contribute (`registry/recipes/`, `$ATTEST_RECIPES_DIR`, `~/.attest/recipes`).

```json
{ "name": "someweirdcrm.lead", "system": "someweirdcrm", "verbs": ["create", "update"], "target": "lead",
  "read": { "method": "GET", "url": "https://api.someweirdcrm.io/v2/leads/{id}", "id": "$.id|$params.lead_id" },
  "compare": { "fields": ["name", "email", "stage"], "checks": [{ "path": "status", "equals": "active" }] },
  "source": "community", "version": 1 }
```

## Propose, review, install

```bash
attest recipes propose --openapi spec.yaml --system someweirdcrm          # POST /x ⇒ GET /x/{id}, fields = body ∩ response
attest recipes propose --mcp-tools tools.json --system tracker            # create_X ⇒ get_X pairs from tools/list
attest recipes propose --openapi spec.yaml --system x --llm --docs api.md # a model proposes compare fields / checks
attest recipes install recipes/proposals/someweirdcrm.json                # after review — into ~/.attest/recipes
attest recipes list
```

Proposals are never installed automatically. The model step (`--llm`, `ANTHROPIC_API_KEY`) only suggests
`compare.fields` and `checks`; the read path comes from the spec or the tool pair. Contribute a reviewed recipe
by PR into `registry/recipes/` with a fake-backed test showing one `verified` and one `unverified` case.
