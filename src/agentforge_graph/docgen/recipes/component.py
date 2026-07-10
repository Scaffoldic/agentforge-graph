"""The ``component`` recipe — document one module/package (feat-016).

Seeds from the structural symbols under the target scope plus any framework
elements (routes/models) rooted there, with file summaries as framing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from agentforge_graph.core import NodeKind

from ..types import DocTarget, DocType, GroundedFact, GroundedPack, SymbolRef
from ._common import symbol_facts
from .base import Recipe

if TYPE_CHECKING:
    from agentforge_graph.ingest import CodeGraph


class ComponentRecipe(Recipe):
    doc_type: ClassVar[DocType] = DocType.COMPONENT

    async def seed(self, cg: CodeGraph, target: DocTarget) -> GroundedPack:
        scope = target.scope or ""
        facts = await symbol_facts(cg, path_prefix=scope, limit=80)

        for r in await cg.routes():
            if r.handler and r.file.startswith(scope):
                facts.append(
                    GroundedFact(
                        text=f"Route {r.method} {r.path_pattern} → handler {r.handler}",
                        ref=SymbolRef(
                            id=r.handler,
                            kind=NodeKind.ROUTE,
                            name=f"{r.method} {r.path_pattern}",
                            path=r.file,
                            span=(r.line, r.line) if r.line else None,
                        ),
                        source="parsed",
                    )
                )
        for m in await cg.models():
            if m.cls and m.file.startswith(scope):
                facts.append(
                    GroundedFact(
                        text=f"DataModel {m.name} ({m.framework})",
                        ref=SymbolRef(
                            id=m.cls,
                            kind=NodeKind.DATA_MODEL,
                            name=m.name,
                            path=m.file,
                            span=(m.line, m.line) if m.line else None,
                        ),
                        source="parsed",
                    )
                )

        notes = [
            f"File summary ({s.path}): {s.text}"
            for s in await cg.summaries(level="file")
            if s.text and s.path.startswith(scope)
        ]
        return GroundedPack(target=target, facts=tuple(facts), notes=tuple(notes))
