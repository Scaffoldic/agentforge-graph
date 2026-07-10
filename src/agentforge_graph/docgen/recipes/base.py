"""Recipe seam — one per doc type, additive (feat-016).

A recipe turns a :class:`DocTarget` into a **seed** :class:`GroundedPack`: the
high-value graph facts worth handing the Agent up front so it does not start
cold. It is pure graph assembly — **no LLM** — so it is unit-testable against a
fixture graph with exact expected facts. The Agent later *expands* the seed by
calling the read-only ckg toolset (chunk 3).

Adding a doc type = a new :class:`Recipe` subclass + one :func:`register` call.
No edits to the generator, the runner, the citation verifier, or other recipes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

from ..errors import DocDisabled
from ..types import DocTarget, DocType, GroundedPack

if TYPE_CHECKING:  # avoid an import cycle — the facade imports docgen (chunk 5)
    from agentforge_graph.ingest import CodeGraph


class Recipe(ABC):
    """Assembles the seed grounded pack for one doc type."""

    doc_type: ClassVar[DocType]

    @abstractmethod
    async def seed(self, cg: CodeGraph, target: DocTarget) -> GroundedPack:
        """Query the graph into a seed pack of citable facts (+ non-citable
        framing ``notes``). Facts are drawn from ``>= parsed`` provenance only;
        llm-sourced material (summaries) belongs in ``notes``."""


RECIPES: dict[DocType, Recipe] = {}


def register(recipe: Recipe) -> Recipe:
    """Register a recipe instance under its ``doc_type``."""
    RECIPES[recipe.doc_type] = recipe
    return recipe


def get_recipe(doc_type: DocType) -> Recipe:
    """The recipe for a doc type, or :class:`DocDisabled` if none is registered."""
    recipe = RECIPES.get(doc_type)
    if recipe is None:
        raise DocDisabled(f"no recipe registered for doc type {doc_type.value!r}")
    return recipe
