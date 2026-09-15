# LangGraph / LangChain

```bash
pip install "attestlayer[langgraph]"
```

```python
from attest.adapters import langgraph as attest_lg

mapping = {"send_email": {"system": "gmail", "verb": "send", "target": "to", "readers": {"gmail": gmail}},
           "update_deal": {"system": "hubspot", "verb": "update", "target": "deal_id"}}

tools = attest_lg.wrap_tools([send_email, update_deal], at, mapping=mapping)   # before building the graph
graph = create_react_agent(model, tools)

attest_lg.wrap(graph, at, mapping=mapping)          # or patch an existing graph's ToolNode(s) in place

agent = create_agent(model, tools, middleware=[attest_lg.AttestMiddleware(at, mapping=mapping)])   # langchain ≥ 1
```

Unmapped tools are inferred from their name. Refusals and rejections come back to the model as an error
`ToolMessage` so the run continues; the ledger records them either way.

## Pausing the graph

```python
from attest.gate.interrupt import InterruptGate
at = Attest(gate=InterruptGate())
graph = create_react_agent(model, tools, checkpointer=MemorySaver())
out = graph.invoke(state, config)                  # out["__interrupt__"][0].value is the confirm request
graph.invoke(Command(resume={"status": "approved", "approver": "ram"}), config)   # or "rejected", or edits
```

See `examples/langgraph_agent.py` for an end-to-end run yielding two `verified` entries.
