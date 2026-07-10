"""The ``design`` recipe — "how it works + why" for a subsystem (feat-016).

Seeds from the subsystem's structural symbols plus the decisions that govern it;
the Agent expands the call graph and rationale via the tools. The highest-
synthesis doc type — it leans hardest on ``require_citations`` + the promote gate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from ..types import DocTarget, DocType, GroundedPack
from ._common import decision_facts, symbol_facts
from .base import Recipe

if TYPE_CHECKING:
    from agentforge_graph.ingest import CodeGraph


class DesignRecipe(Recipe):
    doc_type: ClassVar[DocType] = DocType.DESIGN

    async def seed(self, cg: CodeGraph, target: DocTarget) -> GroundedPack:
        scope = target.scope or ""
        facts = await symbol_facts(cg, path_prefix=scope, limit=60)
        facts.extend(await decision_facts(cg, scope=scope or None))

        notes = [
            f"Summary ({s.path}): {s.text}"
            for s in await cg.summaries()
            if s.text and s.path.startswith(scope)
        ]
        return GroundedPack(target=target, facts=tuple(facts), notes=tuple(notes))
