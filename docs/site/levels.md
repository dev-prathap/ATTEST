# Verification levels

| level | meaning | how |
| --- | --- | --- |
| `verified` | the record in the system of record matches the intent | reviewed recipe or convention read-back compared fields |
| `verified-custom` | your own `verify=` function returned true | you decide what "verified" means |
| `acknowledged` | the API said yes — an id, a success status, a 2xx | nothing was read back |
| `attested-only` | recorded; nothing checkable | no id, no status, no reader |
| `unverified` | **a check ran and contradicted the claimed result** | surfaced loudly; the incident you want to catch |

Rules that keep the ladder honest:

- A check that could not run (network error, missing id, unknown record) **degrades** to `acknowledged` or
  `attested-only` with the error in evidence. Only a contradiction is `unverified`.
- A read-back that finds the record but has nothing intended to compare is `acknowledged` with `exists: true`,
  never `verified`.
- Evidence carries ids, labels and field-level match results — never message bodies.

Coverage is 100 %: every action gets a level. Depth grows per system through recipes, the REST convention
driver, MCP tool pairs, and your own checks.
