"""L3 driver backed by the recipe registry and the customer's pass-through readers."""
from __future__ import annotations

from typing import Any

from attest.descriptor import ActionDescriptor
from attest.verify import recipes
from attest.verify.ladder import ReadBackDriver
from attest.verify.match import MatchReport
from attest.verify.readers import BaseReader, build_all


class RecipeDriver(ReadBackDriver):
    name = "recipe"

    def __init__(self, readers: dict[str, Any] | None = None):
        self.readers: dict[str, BaseReader] = build_all(readers)
        self._pending: dict[str, tuple[recipes.Recipe, Any]] = {}

    def with_readers(self, extra: dict[str, Any] | None) -> RecipeDriver:
        if not extra:
            return self
        d = RecipeDriver()
        d.readers = {**self.readers, **build_all(extra)}
        return d

    def supports(self, d: ActionDescriptor) -> bool:
        return d.system in self.readers and recipes.find(d, d.result) is not None

    def fetch(self, d: ActionDescriptor, result: Any) -> Any:
        recipe = recipes.find(d, result)
        if recipe is None:
            return None
        fetched = recipe.fetch(self.readers[d.system], d, result)
        self._pending[d.id] = (recipe, result)
        return fetched

    def compare(self, d: ActionDescriptor, fetched: Any) -> MatchReport:
        recipe, result = self._pending.pop(d.id, (recipes.find(d, d.result), d.result))
        report = recipe.compare(d, result, fetched)
        report.notes.insert(0, f"recipe={recipe.name}")
        return report

    def recipe_name(self, d: ActionDescriptor) -> str | None:
        r = recipes.find(d, d.result)
        return r.name if r else None
