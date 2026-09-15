# Open recipe registry

Community-contributed, versioned read-back recipes (doc 03 §4 #5). Each JSON file in `recipes/` describes,
for one system and verb, **which read proves the write and what to compare**. They load automatically.

```json
{ "name": "someweirdcrm.lead.create", "system": "someweirdcrm", "verbs": ["create"], "target": "lead",
  "read": { "method": "GET", "url": "https://api.someweirdcrm.io/v2/leads/{id}", "id": "$.id" },
  "compare": { "fields": ["name", "email", "stage"], "checks": [{ "path": "status", "equals": "active" }] },
  "source": "community", "version": 1 }
```

Start from a proposal: `attest recipes propose --openapi spec.yaml --system <name> [--llm]` or
`--mcp-tools tools.json`, review `compare.fields` against the vendor docs, then open a PR adding the file here.
Rules: only fields the read returns unchanged; never compare secrets or bodies; every recipe needs a fake-backed
test in `tests/test_declarative_recipes.py` showing one `verified` and one `unverified` case.
