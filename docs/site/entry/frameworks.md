# Claude Agent SDK, CrewAI, DeerFlow

## Claude Agent SDK — hooks

```python
from claude_agent_sdk import ClaudeAgentOptions, HookMatcher
from attest.adapters import claude_agent_sdk as attest_cl

pre, post = attest_cl.hooks(at, mapping={"mcp__gmail__send_message": {"system": "gmail", "verb": "send", "target": "to"}})
options = ClaudeAgentOptions(hooks={"PreToolUse": [HookMatcher(hooks=[pre])], "PostToolUse": [HookMatcher(hooks=[post])]})
```

PreToolUse decides and gates: a refusal or a human rejection becomes `permissionDecision: "deny"` with the reason;
an approval with edits returns `updatedInput`. PostToolUse verifies the tool response and writes the ledger row.
Tool names like `mcp__gmail__send_message` infer the system from the server segment.

## CrewAI

```python
from attest.adapters import crewai as attest_crew
tools = attest_crew.wrap_tools([send_email_tool, update_deal_tool], at, mapping=mapping)
agent = Agent(role="…", tools=tools)
```

Returns a subclass instance of each tool whose `_run` / `_arun` go through Attest. Positional arguments are
mapped by name so confirm-time edits apply.

## DeerFlow

DeerFlow agents are LangChain agents with a middleware chain; use the middleware, outermost:

```python
from attest.adapters.deerflow import AttestMiddleware
middlewares = [AttestMiddleware(at, mapping=mapping), *deerflow_middlewares]
```

DeerFlow's tool receipts prove a call happened inside the run; Attest proves the world changed and who approved.
