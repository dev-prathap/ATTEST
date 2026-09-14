"""OpenAI Agents SDK + Attest: wrap FunctionTools; run with a real model if OPENAI_API_KEY is set, else
invoke the wrapped tools directly to show the ledger.   ATTEST_AUTO_APPROVE=1 python examples/openai_agent.py"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents import function_tool  # noqa: E402
from agents.tool_context import ToolContext  # noqa: E402

from attest import Attest, SqliteLedger  # noqa: E402
from attest.adapters import openai_agents as attest_oa  # noqa: E402


@function_tool
def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email."""
    return {"id": "m1", "threadId": "t1"}


@function_tool
def update_deal(deal_id: str, dealstage: str) -> dict:
    """Update a HubSpot deal stage."""
    return {"id": deal_id, "properties": {"dealstage": dealstage}}


at = Attest(ledger=SqliteLedger(":memory:"), agent="oa-agent@v1", actor="ram@acme.com")
tools = attest_oa.wrap_tools([send_email, update_deal], at, mapping={
    "send_email": {"system": "gmail", "verb": "send", "target": "to"},
    "update_deal": {"system": "hubspot", "verb": "update", "target": "deal_id"},
})


async def main() -> None:
    if os.environ.get("OPENAI_API_KEY"):
        from agents import Agent, Runner
        agent = Agent(name="followup", instructions="Send the follow-up email then move the deal to proposal_sent.",
                      tools=tools)
        out = await Runner.run(agent, "Email arun@newco.com the proposal (deal 777).")
        print(out.final_output)
    else:
        import agents
        for t, args in ((tools[0], {"to": "arun@newco.com", "subject": "Proposal", "body": "…"}),
                        (tools[1], {"deal_id": "777", "dealstage": "proposal_sent"})):
            ctx = ToolContext(context=None, tool_name=t.name, tool_call_id="c", tool_arguments=json.dumps(args),
                              run_config=agents.RunConfig())
            print(t.name, "→", await t.on_invoke_tool(ctx, json.dumps(args)))
    for e in at.ledger.entries():
        d = e.descriptor
        print(f"#{e.seq} {d['system']}.{d['verb']} → {d['target']}  decision={e.decision} confirm={e.confirm.status} "
              f"level={e.verification.level}")


asyncio.run(main())
