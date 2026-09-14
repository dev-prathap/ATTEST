"""DeerFlow adapter. DeerFlow agents are LangChain (≥1) agents with a middleware chain; Attest plugs in as a
middleware — placed **outermost**, per DeerFlow's own ordering rule for ToolReceiptMiddleware, so nothing
downstream can short-circuit the record.

    from attest.adapters.deerflow import AttestMiddleware
    middlewares = [AttestMiddleware(at, mapping=…), *deerflow_middlewares]

DeerFlow's tool receipts (args/output hashes cited by the model) and Attest's ledger complement each other:
receipts prove a call happened inside the run; Attest proves the world changed and who approved it.
"""
from __future__ import annotations

from attest.adapters.langgraph import AttestMiddleware, wrap_tool, wrap_tools

__all__ = ["AttestMiddleware", "wrap_tool", "wrap_tools"]
