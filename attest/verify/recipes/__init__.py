"""Reviewed read-back recipes: per system, which read proves which write, and what to compare.

A recipe is a small object: `matches(d)` says whether it applies to a descriptor, `fetch(reader, d, result)`
reads the system of record with the caller's credentials, `compare(d, result, fetched)` returns a MatchReport.
Gmail is ported from DO's Google adapter `verify()`; Slack and HubSpot are new field-comparing recipes
(DO only had existence pairs behind the Nango proxy).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from attest.descriptor import ActionDescriptor
from attest.verify.match import MatchReport
from attest.verify.readers import BaseReader


@dataclass(frozen=True)
class Recipe:
    name: str
    system: str
    verbs: tuple[str, ...]
    fetch: Callable[[BaseReader, ActionDescriptor, Any], Any]
    compare: Callable[[ActionDescriptor, Any, Any], MatchReport]
    when: Callable[[ActionDescriptor, Any], bool] | None = None  # extra applicability test
    source: str = "reviewed"

    def matches(self, d: ActionDescriptor, result: Any) -> bool:
        if d.system != self.system or d.verb not in self.verbs:
            return False
        return self.when(d, result) if self.when else True


_REGISTRY: dict[str, list[Recipe]] = {}


def register(recipe: Recipe) -> Recipe:
    _REGISTRY.setdefault(recipe.system, []).append(recipe)
    return recipe


def find(d: ActionDescriptor, result: Any) -> Recipe | None:
    for r in _REGISTRY.get(d.system, []):
        if r.matches(d, result):
            return r
    return None


def all_recipes() -> list[Recipe]:
    return [r for rs in _REGISTRY.values() for r in rs]


def _load() -> None:
    from attest.verify.recipes import gmail, hubspot, slack  # noqa: F401 - registration side effect


_load()
