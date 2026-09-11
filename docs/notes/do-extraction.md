# DO → Attest extraction notes (P0.5)

Read on 2026-09-12 against `/Users/prathap/Dev/lab/DO` (commit `df85d52`, first import) and
`/Users/prathap/Dev/lab/DEER` (clone of `bytedance/deer-flow`, commit `c55f242`).

**Purpose:** map every piece doc 06/08 says we lift, note what actually exists, what must be
decoupled, and what is missing. Corrections to 06/08 are collected at the end.

---

## 0. Source map (corrected paths)

All DO source lives under `app/brain/`, not the repo root.

| Doc 08 says | Actual path | Lines |
| --- | --- | --- |
| `execution/policy.py` | `app/brain/execution/policy.py` | 111 |
| `execution/actions.py` | `app/brain/execution/actions.py` | 436 |
| `connectors/registry.py` | `app/brain/connectors/registry.py` | 235 |
| `connectors/capabilities.py` | `app/brain/connectors/capabilities.py` | 131 |
| `schema.sql` | `app/brain/schema.sql` | 269 |
| "41 `VERIFY_WITH` pairs in actions.py" | `app/brain/connectors/providers/template.py` `VERIFY_WITH` dict, **65 pairs** | lines 75–143 |
| Google read-back (not named in 08) | `app/brain/connectors/providers/google.py` `GoogleConnector.verify()` | lines 542–600 |
| Convention pairing | `app/brain/connectors/providers/template.py` `_auto_pair()` | lines 165–188 |
| Verb classifier | `app/brain/connectors/providers/template.py` `VERB_MAP`, `_verb()`, `_risk()` | lines 20–63, 146–158 |
| Connector contract | `app/brain/connectors/base.py` | 45 |
| Ledger write helper | `app/brain/execution/access.py` `ledger()` | 3 lines |
| DeerFlow receipts | `DEER/backend/packages/harness/deerflow/agents/middlewares/{tool_receipt,tool_receipt_middleware,receipt_verification}.py`, `config/verification_config.py` | 648 total |

Runnable tests in DO: `app/brain/tests/smoke.py` only (integration smoke against a live DB and
runtime; not unit tests). Nothing to lift as tests — P1 writes its own.

---

## 1. Policy engine → `attest.policy`

**Source:** `execution/policy.py` `evaluate_action(cx, org_id, cap, params, actor, owner) -> PolicyResult`.

**Shape (keep as is):**
```python
@dataclass
class PolicyResult:
    decision: str            # Act | Ask | Refuse
    risk_tier: str           # Low | Medium | High | Very high
    requires_confirm: bool
    allow: bool
    reasons: list[str]
```

**Rules as implemented (R0–R4):**

| Rule | What it does | DB coupling |
| --- | --- | --- |
| R0 org permission | `permission` table lookup: `allowed \| approval_required \| blocked` per `(provider, action-or-verb-or-*)`; `blocked` ⇒ Refuse | `SELECT rule FROM permission …` |
| R1 acting on another's connection | `owner != actor` ⇒ reason only, no decision change | none |
| R2 recipient legitimacy | for writes, every email in `to/cc/bcc/email/emails/attendees/recipients` is `internal` (same registered domain as org), `known` (a `company:<domain>` node exists in the graph), or `unknown`. Unknown + `send/share` ⇒ **Refuse**. Unknown + `reply` ⇒ warn. Unknown + calendar with `notify_attendees` ⇒ Ask. | `SELECT domain FROM org`, `SELECT 1 FROM nodes WHERE kind='company'` |
| R3 content completeness | any string param matching `\[[^\]]+\]` ⇒ **Ask** (hold) | none |
| R4 risk tier ⇒ confirm | `risk == low` ⇒ Act, no confirm. Otherwise Act with `requires_confirm=True` (and an extra reason if R0 was `approval_required`) | none |

**Gotchas for extraction:**
- Three SQL touch points must become injected callables: `org_rule(system, verb, action_id) -> str`,
  `org_domain() -> str`, `is_known_domain(domain) -> bool`. Defaults: `allowed`, actor's domain,
  `False`.
- Decision vocabulary is capitalised (`Act/Ask/Refuse`); Attest uses lowercase `act/ask/refuse`.
  Doc 02 says `ask` means "pause for a human"; DO encodes that as `Act + requires_confirm=True`,
  and reserves `Ask` for a hold that needs *input* (placeholder, unknown attendee). Collapse to:
  `refuse` | `ask` (= DO Ask **or** requires_confirm) | `act`. Keep the hold reason so the confirm
  card can distinguish "approve" from "fix and retry".
- R2's Refuse for unknown external send is **hard-coded**, not a policy rule. Doc 03 presents it as
  YAML (`match: {verb:[send,share], target: external} → ask`). Make R2 produce a `target_class`
  (`internal|known|unknown`) on the descriptor and let YAML decide; ship DO's behaviour as the
  default policy file, softened to `ask` rather than `refuse`.
- Uses `tldextract` for registered-domain matching. Keep (small dep) or vendor a public-suffix check.
- Risk tier comes from the capability (`cap.risk`), not computed. In Attest it comes from
  `RISK_BY_VERB` (§3) + overrides on the descriptor.

---

## 2. Read-back verification → `attest.verify`

Two mechanisms exist in DO. Doc 06/08 conflate them.

### 2a. Declarative pairs (`VERIFY_WITH`, 65 entries) — for the template/Nango runtime
Shape: `(integration, action-name) -> {"capability": "<read cap id>", "params": {"<arg>": "$.id" | "$params.x" | "$params.x|literal"}}`.
Reference syntax (`_ref`/`_dig` in actions.py, ~25 lines): `$.<path>` reads the write's result,
`$params.<path>` reads the write's input, `|<default>` fallback. Lift verbatim.

Execution (`_verify_with`): resolve refs → if any resolves empty ⇒ `{"verified": None, "skipped": …}`
→ run the read capability → `verified = status == done and bool(result)`.
**Existence check only.** No field comparison. This is L3-by-existence, not L3-by-match.

Coverage by system:

| System | Pairs | Notes |
| --- | --- | --- |
| Microsoft 365 (outlook, teams, one-drive, sharepoint) | 25 | wave 1 |
| Zoho CRM | 19 | wave 1 |
| Google (mail labels/filters, calendar, drive, docs, sheet) | 11 | create-side only; *send* is not here |
| Slack | 2 | `send-message → get_message_permalink(channel, ts)`, `create-channel → get_channel_info` |
| HubSpot | 3 | `create-contact/deal/company → get`. **No update pairs.** |
| Notion | 2 | create page, create database |
| Linear | 3 | create issue, project, comment |

### 2b. Imperative read-back (`GoogleConnector.verify`) — the direct adapter
Per-action Python that fetches and **compares fields**. This is the real L3 model:

| Action | Read | Match condition |
| --- | --- | --- |
| `gmail_send` / `gmail_reply` | `messages.get(id, metadata To/Subject)` | `SENT` in labels **and** first intended recipient ⊂ `To` header; reply also `threadId` equal |
| `gmail_create_draft` | `drafts.get` | id present |
| `gmail_update_labels` | `messages.get(minimal)` | added ⊂ labels and removed ∩ labels = ∅ |
| `calendar_create/update_event` | `events.get(primary, id)` | `status == confirmed` and summary equal |
| `drive_create_file` / `docs_create_document` | `files.get` | name equal |
| `docs_append_text` | `documents.get` | last 120 chars of written text ⊂ body |
| `drive_share_file` | `permissions.list` | email present, returns role |
| `contacts_create/update` | `people.get` | field-by-field |

Every branch returns `{"verified": bool, ...evidence}`; exceptions ⇒ `{"verified": False, "error"}`.

**Extraction plan:**
- Driver interface (P1.2.1): `fetch(result, params) -> fetched` + `compare(intent, fetched) -> MatchReport`.
  2a pairs become `ConventionRecipe(read_cap, arg_refs)` with `compare = exists`.
  2b branches become `Recipe` objects with field comparators; port Gmail (P1.2.3) from here.
- Level mapping: 2b match ⇒ `verified` (L3). 2a existence ⇒ `verified` only if the recipe carries
  at least one field comparator; otherwise record as `acknowledged+exists` — decide in P1.2 whether
  that is L3 or a new L3-lite. **Do not** call existence-only "verified" silently (decision 4).
- `verified: None` + `skipped` ⇒ `attested-only`/`acknowledged`, never `unverified`.
  `verified: False` from a successful fetch ⇒ **`unverified`** (contradiction). Fetch error ⇒
  `acknowledged` with error evidence, not `unverified` (DO currently conflates these).
- Slack and HubSpot recipes in DO run through the Nango proxy (`app/actions` runtime). Attest
  pass-through mode needs direct-SDK equivalents: Slack `chat.postMessage → conversations.history(channel, latest=ts, inclusive, limit=1)`;
  HubSpot `crm.objects.<type>.basic_api.get_by_id` with `properties=` from the write's params for
  field compare. HubSpot **update** read-back must be written new (convention driver can cover it).

### 2c. Convention driver (`_auto_pair`) — lift verbatim
`create-X | update-X → get-X` when `get-X` has exactly one required param ending in `id`.
Create binds it to `$.id`; update binds to `$params.<same name>`. Marked `"auto": True`.
Docstring principle to keep: *"A wrong guess can only make a write read as unverified — never as verified."*
Generalise for REST: `POST /v2/leads → GET /v2/leads/{id}`, `PATCH /x/{id} → GET /x/{id}`.

---

## 3. Registry, verbs, risk → `attest.registry`

**From `capabilities.py`:**
```python
READ_VERBS  = {"search", "get", "list"}
WRITE_VERBS = {"send", "reply", "draft", "create", "update", "share", "upload", "delete"}
RISK_ORDER  = {"low": 0, "medium": 1, "high": 2, "very_high": 3}
```
Doc 03's verb list adds `pay`, `approve`, `execute`, `write`. Extend `WRITE_VERBS` with these;
`RISK_BY_VERB` gets `pay: very_high`, `approve: high`, `execute: high`, `write: medium`.

**From `template.py`:**
- `VERB_MAP` — ~70 first-word aliases → canonical verb (`post→send`, `invite→create`, `archive→update`,
  `cancel→delete`, `grant→share` …). `GET_WORDS`, `SEARCH_WORDS`. `_first()` strips `batch-`/`bulk-`.
- `_verb(name)`: search/list/get words, else `VERB_MAP.get(first, "update")`.
  **Attest change:** unknown first word ⇒ `write`, not `update` (doc 03 §3).
- `RISK_BY_VERB`: search/get/list low · update medium · send/reply/create/share high · delete very_high.
- `_risk()`: unknown first word ⇒ `high` ("unknown side effect → confirm"). Keep.
- `RISK_OVERRIDES` / `VERB_OVERRIDES` (~30 reviewed entries, e.g. `slack_add_reaction: medium`,
  `onedrive_invite_recipients: share`). Lift as the seed of the reviewed-override table.
- Tokeniser works on hyphenated Nango action names (`send-message`). Attest needs the same for
  `snake_case` MCP tool names (`gmail_send_message`), dotted SDK paths (`hubspot.crm.deals.update`),
  and `METHOD + URL` (`POST …/messages/send`). Write one `tokens(name_or_url) -> [str]` and reuse
  `_verb` over the tokens; detect system from the first token / hostname.

**From `registry.py`:** `SYSTEM_LABELS` (~35 systems) and `TEMPLATE_APPS` pids give the initial
system vocabulary. Everything else there is Nango/OAuth config — not needed.

**`Capability` dataclass** is DO's per-action schema (params, scopes, `idempotent`, `returns`).
Attest's `ActionDescriptor` is per-*invocation*. Don't lift `Capability`; lift only
`is_write`, `verify_with`, and the risk fields as descriptor attributes.

---

## 4. Ledger and data model → `attest.ledger` + cloud schema

**`ledger_event`** (schema.sql:171): `id bigserial, org_id, task_id, type text, detail jsonb, at`.
Event types used in actions.py: `ACTION_STARTED`, `ACTION_EXECUTED`, `ACTION_VERIFIED`, `ACTION_FAILED`
(plus access-request lifecycle events in access.py). **No hash chain, no signature.** Decision 12
(hash-chained) is new work; the DO table is only a shape hint.

**`action_run`** (schema.sql:197) is the closer match to Attest's `action` + `execution` +
`verification` rows: `actor, owner, provider, capability, params jsonb, status, risk, attempts,
idempotency_key, result jsonb, verification jsonb, verified bool, summary, error, task_id, run_id`.
Statuses: `pending|needs_confirm|held|refused|executing|done|failed`.
- Lift: idempotency key with partial unique index; retry journal (`attempts`); `status` vocabulary
  maps onto Attest's decision + execution states.
- Change: `verified bool` ⇒ `level text` (decision 4). Split into the three tables in doc 04.
- Params are stored **in full** in DO. Attest default is `params_hash` + allow-listed preview
  (doc 07 open question). Note `ActionOutcome.to_dict()` already exposes everything — cloud sink must
  redact.

**`permission`** (`org_id, provider, action, rule`) is R0's backing table → becomes one YAML rule
form: `match: {system, verb|action} → decision`.

**Not lifting:** `org`, `nodes/edges`, `communications`, `memory`, `connection`, `task`,
`access_request`, `app_access`, `action_plan`, `org_sync`, `brief_dismiss` — DO's graph, memory and
collaboration model. Better Auth org/user tables live in `app/web`, not in this schema; the
cloud auth choice (doc 07) is still open and nothing here constrains it.

---

## 5. Action engine (`run_action`) — pattern reference only

Order in DO: connection+scope → access (other's connection) → missing params → **policy** →
**confirm gate** (`needs_confirm` unless `confirmed=True`) → idempotency → execute with bounded
retry (non-idempotent retries only on 429) → **verify** → journal + ledger → memory.

What carries into `Attest.action()` / the decorator:
- gate-before-execute ordering and `confirmed` re-entry (sync-block mode = call again with the token);
- soft-error detection (`result.get("error")` with ≤2 keys, Slack-style) ⇒ failed, not verified;
- `summarize(action, params, result)` one-liner for cards and ledger rows;
- `verified is False ⇒ summary += " — but read-back verification did not confirm it"` (loud).

What does **not** carry: DO executes the vendor call itself (`conn.execute`). Attest never does
(decision 2). The decorator's "execute" step is the customer's function body.

---

## 6. DeerFlow — what is actually there

`receipt_verification.py` checks whether a subagent's **report text cites** receipt ids
(`[r3 write_file]`). It is citation honesty for prose, not outcome read-back. Lineage claim in
doc 01/06 ("verification patterns") is overstated; the reusable parts are:

- **`ToolReceipt` shape** (`tool_receipt.py`): `tool_call_id, tool_name, status, args_sha256,
  output_sha256, output_bytes, created_at`. Adopt `args_sha256` as Attest's `params_hash`
  (`json.dumps(args, sort_keys=True, default=str)` → sha256, 16 hex). Adopt `output_sha256` for
  the execution result.
- **Stamping discipline** (`tool_receipt_middleware.py`): receipt key is runtime-owned and always
  overwritten so a tool cannot forge its own evidence; stamping failure is logged loudly, never
  swallowed silently. Same rule for Attest's ledger sink.
- **Anti-automation-bias line** rendered with every ledger: *"receipts record that a call happened
  and its status; they do not validate claim correctness."* Reuse the wording on L0/L1 entries.
- **UNVERIFIED vocabulary** (`render_citation_verdict`): a claim without evidence is `UNVERIFIED`,
  stated in caps, first-class. Matches decision 4.
- **LangGraph middleware pattern**: `AgentMiddleware.wrap_tool_call / awrap_tool_call` wrapping every
  tool node — this is the shape for `attest.langgraph.wrap(graph)` (P1.2.8), and the outermost-layer
  ordering note applies (Attest must wrap outside any middleware that can short-circuit results).

Not present in DEER: MCP proxying as a standalone binary (DEER has an MCP *client*), Slack/Telegram
confirm cards as reusable modules (channel code is app-specific). P1.3.2 and P1.3.6 are new code.

---

## 7. Corrections to docs 06 / 08

| Where | Says | Actual |
| --- | --- | --- |
| 06 reuse table, 08 P0.5, P1.2.1 | `execution/actions.py` holds 41 `VERIFY_WITH` pairs | `connectors/providers/template.py` holds 65; `actions.py` holds the resolver (`_ref/_dig/_verify_with`) |
| 08 P1.2.3 | Gmail recipe from "DO Google deep adapter" | correct file is `providers/google.py` `verify()`; it is imperative, not a pair |
| 08 P1.2.4 | Slack pairs | 2 pairs, existence-only, via Nango proxy — direct-SDK read-back is new |
| 08 P1.2.5 | HubSpot create/update pairs | 3 create pairs only; update read-back is new or convention-derived |
| 06 reuse table | `schema (ledger_event, action_run, permission)` | `ledger_event` has no chain; `action_run` is the useful shape |
| 06 reuse table | DO Better Auth orgs | not in `app/brain`; lives in `app/web` (Next.js); not reviewed here |
| 01/06 | DeerFlow "verification patterns" | citation verification of report text; reuse receipt shape + discipline only |
| 03 §7 | unknown-external send ⇒ `ask` via YAML | DO hard-codes **Refuse**; Attest should classify target and let YAML decide |
| 08 P0.5 | all paths | prefix `app/brain/` |

---

## 8. P1.1 inputs ready to copy

Concrete artefacts to start week 1 from (all under `app/brain/`):
- `connectors/providers/template.py` lines 20–63 → `attest/registry/verbs.py` (VERB_MAP, RISK_BY_VERB, overrides).
- `connectors/providers/template.py` lines 146–158 → `_verb`, `_risk` (change unknown ⇒ `write`).
- `connectors/providers/template.py` lines 165–188 → `attest/verify/drivers/convention.py`.
- `connectors/providers/template.py` lines 75–143 → `attest/verify/recipes/seed.json` (65 pairs, tag `source: reviewed`).
- `execution/actions.py` lines 297–317 → `attest/verify/refs.py` (`$.`, `$params.`, `|default`).
- `execution/policy.py` whole file → `attest/policy/rules.py` with the three callables injected.
- `connectors/providers/google.py` lines 542–600 → `attest/verify/recipes/gmail.py` (P1.2.3).
- `DEER …/tool_receipt.py` `make_tool_receipt` → `attest/ledger/models.py` hashing.
