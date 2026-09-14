# OpenAI Agents SDK

```bash
pip install "attest[openai]"
```

```python
from agents import Agent, function_tool
from attest.adapters import openai_agents as attest_oa

tools = attest_oa.wrap_tools([send_email, update_deal], at, mapping=mapping)
agent = Agent(name="followup", tools=tools)
```

With a blocking gate the tool call waits for the human. With `StoreGate(wait=False)` it returns
`{"status": "pending_confirmation", "resume_token": …}` to the model; your app later runs
`await attest_oa.resume(at, token)` to execute once approved.
