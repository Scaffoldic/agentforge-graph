"""The ``ai-context`` recipe — orient an AI assistant to the codebase (feat-016).

Seeds the agent-context draft (CLAUDE.md / AGENTS.md) with the repo's most
central symbols and its recorded decisions, so the generated file points a coding
agent at the real structure + conventions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from ..types import DocTarget, DocType, GroundedFact, GroundedPack, SymbolRef
from ._common import decision_facts
from .base import Recipe

if TYPE_CHECKING:
    from agentforge_graph.ingest import CodeGraph

_TOP_K = 30


class AiContextRecipe(Recipe):
    doc_type: ClassVar[DocType] = DocType.AI_CONTEXT

    async def seed(self, cg: CodeGraph, target: DocTarget) -> GroundedPack:
        facts: list[GroundedFact] = []
        for rs in await cg.ranked_symbols(k=_TOP_K):
            facts.append(
                GroundedFact(
                    text=f"{rs.name} — {rs.kind.value} in {rs.path}",
                    ref=SymbolRef(id=rs.id, kind=rs.kind, name=rs.name, path=rs.path),
                    source="parsed",
                )
            )
        facts.extend(await decision_facts(cg))

        notes = [f"Repo summary: {s.text}" for s in await cg.summaries(level="repo") if s.text]
        return GroundedPack(target=target, facts=tuple(facts), notes=tuple(notes))
