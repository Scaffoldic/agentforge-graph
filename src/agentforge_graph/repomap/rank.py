"""Rank symbols by structural importance: project a provenance-weighted
symbol→symbol digraph (CALLS/REFERENCES/INHERITS) and run (personalized)
PageRank — Aider's recipe. Deterministic and LLM-free.

PageRank is a small dependency-free power iteration (networkx's `pagerank`
pulls in scipy/numpy, which we don't want in the engine for a 20-line algo).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from pydantic import BaseModel

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, Source, SymbolID
from agentforge_graph.store import Store

_RANK_EDGES = [EdgeKind.CALLS, EdgeKind.REFERENCES, EdgeKind.INHERITS]
_ALL = 10_000_000


class RankedSymbol(BaseModel):
    id: str
    name: str
    kind: NodeKind
    path: str
    rank: float
    signature: str


def _edge_weight(weights: dict[str, float], source: Source) -> float:
    return weights.get(source.value, 0.5)


def _pagerank(
    nodes: list[str],
    out_edges: dict[str, dict[str, float]],
    damping: float,
    personalization: dict[str, float] | None,
    max_iter: int = 100,
    tol: float = 1e-9,
) -> dict[str, float]:
    n = len(nodes)
    if n == 0:
        return {}
    if personalization and sum(personalization.values()) > 0:
        total = sum(personalization.values())
        teleport = {nid: personalization.get(nid, 0.0) / total for nid in nodes}
    else:
        teleport = {nid: 1.0 / n for nid in nodes}
    rank = {nid: 1.0 / n for nid in nodes}
    out_sum = {src: sum(dsts.values()) for src, dsts in out_edges.items()}
    for _ in range(max_iter):
        nxt = {nid: (1.0 - damping) * teleport[nid] for nid in nodes}
        dangling = sum(rank[nid] for nid in nodes if out_sum.get(nid, 0.0) == 0.0)
        for nid in nodes:
            nxt[nid] += damping * dangling * teleport[nid]
        for src, dsts in out_edges.items():
            total = out_sum[src]
            if total == 0.0:
                continue
            share = damping * rank[src] / total
            for dst, weight in dsts.items():
                nxt[dst] += share * weight
        err = sum(abs(nxt[nid] - rank[nid]) for nid in nodes)
        rank = nxt
        if err < tol:
            break
    return rank


async def rank_symbols(
    store: Store,
    kinds: list[NodeKind],
    damping: float,
    edge_weights: dict[str, float],
    focus: Sequence[str] | None = None,
    scope: str | None = None,
) -> list[RankedSymbol]:
    nodes = (await store.graph.query(GraphQuery(kinds=kinds, limit=_ALL))).nodes
    if scope is not None:
        nodes = [n for n in nodes if SymbolID.parse(n.id).path.startswith(scope)]
    by_id = {n.id: n for n in nodes}
    if not by_id:
        return []

    out_edges: dict[str, dict[str, float]] = defaultdict(dict)
    for node in nodes:
        for edge in await store.graph.adjacent(node.id, _RANK_EDGES, "out"):
            if edge.dst not in by_id:
                continue
            w = _edge_weight(edge_weights, edge.provenance.source)
            out_edges[edge.src][edge.dst] = out_edges[edge.src].get(edge.dst, 0.0) + w

    personalization = None
    if focus:
        focus_ids = _expand_focus(focus, set(by_id))
        if focus_ids:
            personalization = {nid: (1.0 if nid in focus_ids else 0.0) for nid in by_id}

    scores = _pagerank(list(by_id), dict(out_edges), damping, personalization)
    ranked = [
        RankedSymbol(
            id=node.id,
            name=node.name,
            kind=node.kind,
            path=SymbolID.parse(node.id).path,
            rank=scores.get(node.id, 0.0),
            signature=str(node.attrs.get("signature", "")),
        )
        for node in nodes
    ]
    ranked.sort(key=lambda r: (-r.rank, r.id))  # id tiebreak for determinism
    return ranked


def _expand_focus(focus: Sequence[str], ids: set[str]) -> set[str]:
    matched: set[str] = set()
    paths: set[str] = set()
    for f in focus:
        if f in ids:
            matched.add(f)
        else:
            paths.add(f)
    if paths:
        for nid in ids:
            p = SymbolID.parse(nid).path
            if any(p == fp or p.startswith(fp) for fp in paths):
                matched.add(nid)
    return matched
