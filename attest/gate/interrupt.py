"""LangGraph async-interrupt gate (doc 03 §6). The graph pauses on `interrupt()` with the confirm request as
payload; the operator resumes with `Command(resume={"status": "approved"})` (or "rejected", or
{"status": "edited", "edits": {...}}), and the tool node replays through Attest with the decision in hand.

    at = Attest(gate=InterruptGate())
    tools = attest_lg.wrap_tools(tools, at, mapping=…)
    graph = create_react_agent(model, tools, checkpointer=MemorySaver())
    graph.invoke(…, config)                       # → state.tasks[0].interrupts[0].value is the ConfirmRequest dict
    graph.invoke(Command(resume={"status": "approved", "approver": "ram"}), config)
"""
from __future__ import annotations

from attest.gate import ConfirmDecision, ConfirmRequest


class InterruptGate:
    name = "interrupt"

    def __init__(self, *, store=None, notifiers=None):
        """Optionally also persist + notify (Slack/inbox) so humans can see the request outside the graph; the
        decision still arrives through `Command(resume=…)`."""
        self.store, self.notifiers = store, list(notifiers or [])

    def confirm(self, request: ConfirmRequest) -> ConfirmDecision:
        from langgraph.types import interrupt
        request.channel = self.name
        existing = None
        if self.store is not None:
            d = request.descriptor
            existing = self.store.find_pending(d.qualified_name, d.params_hash)  # replayed node: same request
            if existing is None:
                self.store.create(request)
                for n in self.notifiers:
                    n.notify(request, self.store)
        value = interrupt(request.to_dict())
        decision = ConfirmDecision.from_dict(value, channel=self.name)
        if self.store is not None:
            self.store.decide((existing or {}).get("id") or request.id, decision)
        return decision

    async def aconfirm(self, request: ConfirmRequest) -> ConfirmDecision:
        return self.confirm(request)
