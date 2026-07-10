"""The ``architecture`` recipe — a system-overview seed (feat-016).

Seeds the Agent with the repository's *shape*: its most central symbols
(feat-007 PageRank), its framework topology (routes/models, feat-011), and — as
non-citable framing — its repo-level summary (feat-012, llm-sourced) and DI
services. Structural facts are ``>= parsed`` by construction (PageRank ranks code
symbols over CALLS/REFERENCES/INHERITS; llm nodes are never in that set), so the
seed carries no llm fact as ground truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from agentforge_graph.core import NodeKind

from ..types import DocTarget, DocType, GroundedFact, GroundedPack, SymbolRef
from .base import Recipe

if TYPE_CHECKING:
    from agentforge_graph.ingest import CodeGraph

#: How many top-ranked symbols to seed. The Agent expands beyond these via tools.
_TOP_K = 40


class ArchitectureRecipe(Recipe):
    doc_type: ClassVar[DocType] = DocType.ARCHITECTURE

    async def seed(self, cg: CodeGraph, target: DocTarget) -> GroundedPack:
        facts: list[GroundedFact] = []

        # Most central symbols — the orientation backbone.
        for rs in await cg.ranked_symbols(k=_TOP_K):
            sig = rs.signature.strip() if rs.signature else rs.name
            facts.append(
                GroundedFact(
                    text=f"{rs.name} — {rs.kind.value} in {rs.path}: {sig}",
                    ref=SymbolRef(id=rs.id, kind=rs.kind, name=rs.name, path=rs.path),
                    source="parsed",
                )
            )

        # Framework topology (feat-011): routes cite their handler symbol.
        for r in await cg.routes():
            if not r.handler:
                continue
            facts.append(
                GroundedFact(
                    text=f"Route {r.method} {r.path_pattern} → handler {r.handler} ({r.framework})",
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

        # Data models cite their backing class symbol.
        for m in await cg.models():
            if not m.cls:
                continue
            fields = ", ".join(m.fields[:8]) if m.fields else ""
            facts.append(
                GroundedFact(
                    text=f"DataModel {m.name} ({m.framework}) fields: {fields}",
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

        # Non-citable framing: the repo summary (llm) + DI services.
        notes: list[str] = []
        for s in await cg.summaries(level="repo"):
            if s.text:
                notes.append(f"Repo summary: {s.text}")
        for svc in await cg.services():
            sites = len(svc.injected_into)
            notes.append(f"Service {svc.name} ({svc.framework}) injected into {sites} site(s)")

        return GroundedPack(target=target, facts=tuple(facts), notes=tuple(notes))
