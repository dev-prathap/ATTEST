# Read-back recipes

Attest reads back with the credentials the agent already holds — in-process, never through the cloud.

```python
at = Attest(readers={"gmail": gmail_service_or_token, "slack": web_client_or_token, "hubspot": client_or_token},
            http_get=lambda url, params=None: session.get(url, params=params).json())
```

| system | write | read-back | compares |
| --- | --- | --- | --- |
| gmail | send / reply | `messages.get` | SENT label, every intended recipient in To/Cc, subject, reply thread |
| gmail | create draft | `drafts.get` | exists, recipients, subject |
| gmail | update labels | `messages.get` | added ⊂ labels, removed ∩ labels = ∅ |
| slack | send | `conversations.history` / `.replies` | ts, text, thread_ts |
| slack | create channel | `conversations.info` | exists, name, is_private |
| hubspot | create / update any object | `GET crm/v3/objects/{type}/{id}` | id, every intended property |
| calendar | create / update event | `events.get` | confirmed, summary, start / end, attendees |
| drive | file / share | `files.get` / `permissions.list` | name, parents, not trashed / email present, role |
| docs | create / append | `documents.get` | title, appended text present |
| sheets | create / write values | `spreadsheets.get` / `values.get` | title, every written row present |
| notion | page / database | `pages.retrieve` / `databases.retrieve` | properties (title, status, select, text…), parent |
| linear | issue / project / comment | GraphQL | title, priority, state, assignee, team, body |
| outlook | send / event | sent-items search / `me/events/{id}` | recipients, subject / start, attendees |
| teams | send | channel / chat message | text |
| any REST API | create / update | convention `GET <url>/<id>` | id, every intended field the record carries |
| any REST API with a spec | create / update | `OpenApiDriver(spec, http_get)` | spec-derived read path; never guesses |
| any MCP server | create / update | tool pair `create_X` ⇒ `get_X` | id, overlapping fields |

Readers accept the vendor SDK object (duck-typed, no vendor import), a bearer token (stdlib HTTP), or any
`fetch(path, params)` callable. Every reader also accepts a `fetch(path, params)` callable, so any HTTP client (or a test double) works.
