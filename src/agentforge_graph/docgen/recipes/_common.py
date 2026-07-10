"""Shared seed-assembly helpers for the recipes (feat-016).

Graph-based (no embeddings), provenance-floored at ``>= parsed`` — so seeds are
deterministic and credential-free, and no llm-sourced fact enters as ground
truth. The Agent expands beyond the seed via the tools.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentforge_graph.core import GraphQuery, NodeKind, Source, SymbolID

from ..types import GroundedFact, SymbolRef

if TYPE_CHECKING:
    from agentforge_graph.core import Node
    from agentforge_graph.ingest import CodeGraph

_STRUCTURAL = [
    NodeKind.CLASS,
    NodeKind.INTERFACE,
    NodeKind.FUNCTION,
    NodeKind.METHOD,
    NodeKind.TYPE_ALIAS,
    NodeKind.VARIABLE,
]


def node_ref(node: Node) -> SymbolRef:
    return SymbolRef(
        id=node.id,
        kind=node.kind,
        name=node.name,
        path=SymbolID.parse(node.id).path,
        span=node.span,
    )


async def symbol_facts(
    cg: CodeGraph, *, path_prefix: str = "", limit: int = 60
) -> list[GroundedFact]:
    """Structural symbols under ``path_prefix`` (whole repo when empty), each a
    citable ``>= parsed`` fact."""
    res = await cg.store.graph.query(
        GraphQuery(
            kinds=_STRUCTURAL,
            path_prefix=path_prefix or None,
            min_source=Source.PARSED,
            limit=limit,
        )
    )
    facts: list[GroundedFact] = []
    for n in res.nodes:
        ref = node_ref(n)
        sig = str(n.attrs.get("signature", "")).strip() or n.name
        facts.append(
            GroundedFact(
                text=f"{n.name} — {n.kind.value} in {ref.path}: {sig}",
                ref=ref,
                source=n.provenance.source.value,
            )
        )
    return facts


async def decision_facts(cg: CodeGraph, scope: str | None = None) -> list[GroundedFact]:
    """ADR decisions (optionally scoped) as citable facts."""
    facts: list[GroundedFact] = []
    for d in await cg.decisions(scope=scope):
        ref = SymbolRef(id=d.id, kind=NodeKind.DECISION, name=d.title or d.adr_id, path=d.path)
        text = f"Decision {d.adr_id} '{d.title}' ({d.status}) governs {len(d.governs)} symbol(s)"
        facts.append(GroundedFact(text=text, ref=ref, source="parsed"))
    return facts
