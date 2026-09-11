"""The Action Descriptor — the one shape every entry point normalizes to (doc 03 §1).

Policy, gate, verify and ledger operate only on this. Supporting a new framework or app
means mapping to the descriptor; the core never changes.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field

Verb = Literal[
    "read", "search", "get", "list",
    "create", "update", "delete", "send", "reply", "share", "upload",
    "pay", "approve", "execute", "write",
]
READ_VERBS: frozenset[str] = frozenset({"read", "search", "get", "list"})
WRITE_VERBS: frozenset[str] = frozenset(
    {"create", "update", "delete", "send", "reply", "share", "upload", "pay", "approve", "execute", "write"}
)

RiskTier = Literal["low", "medium", "high", "very_high"]
RISK_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "very_high": 3}
RISK_LABEL: dict[str, str] = {"low": "Low", "medium": "Medium", "high": "High", "very_high": "Very high"}

TargetClass = Literal["internal", "known", "external", "none"]

_HASH_LEN = 16


def canonical_json(obj: Any) -> str:
    """Deterministic JSON (sorted keys, str() for non-JSON types) — the only serialization we hash."""
    return json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))


def short_hash(obj: Any) -> str:
    """sha256 of the canonical JSON, first 16 hex chars (DeerFlow receipt convention)."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()[:_HASH_LEN]


def full_hash(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def new_id(prefix: str = "act") -> str:
    return f"{prefix}_{uuid4().hex[:20]}"


class ActionDescriptor(BaseModel):
    """One agent action, normalized. `result` is filled after the customer's tool executes."""

    id: str = Field(default_factory=lambda: new_id("act"))
    system: str = "unknown"
    verb: Verb = "write"
    target: str | None = None
    target_class: TargetClass = "none"
    params: dict[str, Any] = Field(default_factory=dict)
    actor: str | None = None
    owner: str | None = None  # whose connection/credential runs it, when not the actor
    agent: str | None = None
    run_id: str | None = None
    risk: RiskTier | None = None  # explicit override; otherwise derived from the verb
    result: Any | None = None
    source: str = "manual"  # how system/verb were determined: manual|mcp|url|sdk|heuristic
    extra: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def params_hash(self) -> str:
        return short_hash(self.params)

    @property
    def is_write(self) -> bool:
        return self.verb in WRITE_VERBS

    @property
    def qualified_name(self) -> str:
        return f"{self.system}.{self.verb}" + (f":{self.target}" if self.target else "")

    def with_result(self, result: Any) -> ActionDescriptor:
        return self.model_copy(update={"result": result})

    def to_ledger(self) -> dict[str, Any]:
        """Descriptor as stored: no raw params, no raw result — hashes only."""
        d = self.model_dump(mode="json", exclude={"params", "result", "created_at"})
        d["params_hash"] = self.params_hash
        return d
