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


def _is_private_name(name: str) -> bool:
    """A leading-underscore name is private — except dunders (``__init__``,
    ``__call__``), which are public protocol surface."""
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _is_private_module(path: str) -> bool:
    """A ``_``-prefixed module is internal (``_compat.py``, ``_winconsole.py``).
    ``__init__`` is the package root — the de-facto public surface, not private."""
    stem = path.rsplit("/", 1)[-1].split(".", 1)[0]
    return stem.startswith("_") and stem != "__init__"


def _privacy_multiplier(name: str, path: str, public_bias: float) -> float:
    """ENH-007: a display-rank weight (not a filter) that demotes clearly-private
    symbols. ``public_bias`` in [0, 1]; 0 disables. Private → ``1 - public_bias``."""
    if public_bias <= 0.0:
        return 1.0
    if _is_private_name(name) or _is_private_module(path):
        return max(0.0, 1.0 - public_bias)
    return 1.0


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
    public_bias: float = 0.0,
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
    ranked = []
    for node in nodes:
        path = SymbolID.parse(node.id).path
        # ENH-007: bias the *display* rank toward the public API. Applied after
        # PageRank so the graph propagation is unchanged — private hubs still
        # pass their centrality on; they just sort lower themselves.
        rank = scores.get(node.id, 0.0) * _privacy_multiplier(node.name, path, public_bias)
        ranked.append(
            RankedSymbol(
                id=node.id,
                name=node.name,
                kind=node.kind,
                path=path,
                rank=rank,
                signature=str(node.attrs.get("signature", "")),
            )
        )
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
