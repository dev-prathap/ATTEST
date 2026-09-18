# LangChain integrations page — PR draft

**Target:** `langchain-ai/langchain` docs → Integrations → Tools/Toolkits (or "Human-in-the-loop" section)
**Title:** docs: add Attest (action verification + human confirmation for tools)

## Attest

[Attest](https://github.com/dev-prathap/ATTEST) wraps LangChain tools so every call is decided by policy,
gated behind a human when it matters, **verified by reading back from the system of record**, and recorded in a
hash-chained ledger. It never executes the action — your tool does.

### Installation

```bash
pip install "attestlayer[langgraph]"
```

### Wrap tools

```python
from attest import Attest
from attest.adapters import langgraph as attest_lg

at = Attest(agent="followup-agent@v3", readers={"gmail": gmail_service})
tools = attest_lg.wrap_tools([send_email, update_deal], at, mapping={
    "send_email": {"system": "gmail", "verb": "send", "target": "to"},
    "update_deal": {"system": "hubspot", "verb": "update", "target": "deal_id"},
})
agent = create_react_agent(model, tools)
```

### Middleware (langchain ≥ 1.0)

```python
from langchain.agents import create_agent
agent = create_agent(model, tools, middleware=[attest_lg.AttestMiddleware(at, mapping=mapping)])
```

### Pause with `interrupt`

```python
from attest.gate.interrupt import InterruptGate
at = Attest(gate=InterruptGate())
out = graph.invoke(state, config)                                   # out["__interrupt__"][0].value
graph.invoke(Command(resume={"status": "approved"}), config)
```

Refusals and rejections return to the model as error `ToolMessage`s; every action produces a ledger entry with
a verification level (`verified`, `acknowledged`, `unverified`, …) and evidence.

**API reference:** https://github.com/dev-prathap/ATTEST/blob/main/attest/README.md
