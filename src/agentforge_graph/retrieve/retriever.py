"""``Retriever`` — vector entry → typed graph expansion → provenance-weighted
merge. Deterministic and LLM-free; the single retrieval surface feat-008 and
the enrichers ride on.
"""

from __future__ import annotations

from typing import Literal

from agentforge_graph.config import RetrieveConfig
from agentforge_graph.core import Direction, EdgeKind, Node, Source, SymbolID
from agentforge_graph.embed import Embedder
from agentforge_graph.store import Store

from .pack import ContextItem, ContextPack
from .rerank import NoopReranker, Reranker
from .scoring import dedupe_max, edge_weight, step_score

Mode = Literal["context", "impact", "definition", "similar"]

# Trust order for the min_provenance filter: llm < parsed < resolved <= manual
# (human-asserted facts are trusted; ADR-0004 / spec §2). Distinct from
# GraphQuery.min_source and from the scoring edge_weights.
_RANK: dict[Source, int] = {Source.LLM: 0, Source.PARSED: 1, Source.RESOLVED: 2, Source.MANUAL: 3}
_FLOOR: dict[str, int] = {"parsed": 1, "resolved": 2}

_MODE_EDGES: dict[Mode, tuple[list[EdgeKind], Direction]] = {
    "context": (
        [EdgeKind.CALLS, EdgeKind.CONTAINS, EdgeKind.INHERITS, EdgeKind.REFERENCES],
        "both",
    ),
    "impact": ([EdgeKind.CALLS, EdgeKind.IMPORTS, EdgeKind.IMPLEMENTS], "in"),
    "definition": ([EdgeKind.CONTAINS, EdgeKind.CHUNK_OF], "both"),
    "similar": ([], "both"),
}


class Retriever:
    def __init__(
        self,
        store: Store,
        embedder: Embedder,
        config: RetrieveConfig,
        reranker: Reranker | None = None,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.config = config
        self.reranker: Reranker = reranker or NoopReranker()

    async def retrieve(
        self,
        query: str | None = None,
        symbol: str | None = None,
        mode: Mode = "context",
        k: int | None = None,
        depth: int | None = None,
        edge_kinds: list[EdgeKind] | None = None,
        min_provenance: Literal["parsed", "resolved"] | None = None,
        include_llm_facts: bool = True,
    ) -> ContextPack:
        cfg = self.config
        k = cfg.k if k is None else k
        depth = cfg.depth if depth is None else depth
        items: list[ContextItem] = []
        notes: list[str] = []
        seeds: dict[str, float] = {}

        # --- entry ---
        if query is not None:
            qvec = (await self.embedder.embed([query], "query"))[0]
            for hit in await self.store.vectors.search(qvec, k):
                node = await self.store.graph.get(hit.ref)
                if node is None:
                    continue
                items.append(self._item(node, hit.score, [f"vector hit {hit.score:.2f}"]))
                if mode != "similar":
                    for edge in await self.store.graph.adjacent(
                        hit.ref, [EdgeKind.CHUNK_OF], "out"
                    ):
                        seeds[edge.dst] = max(seeds.get(edge.dst, 0.0), hit.score)
        if symbol is not None:
            seeds[symbol] = max(seeds.get(symbol, 0.0), 1.0)

        for sid, score in list(seeds.items()):
            node = await self.store.graph.get(sid)
            if node is None:
                del seeds[sid]
                continue
            items.append(self._item(node, score, ["entry"]))

        # --- expand ---
        kinds, direction = _MODE_EDGES[mode]
        if edge_kinds is not None:
            kinds = edge_kinds
        if mode != "similar" and depth > 0 and seeds:
            await self._expand(seeds, kinds, direction, depth, items, notes)

        # --- merge ---
        items = self._filter(items, min_provenance, include_llm_facts)
        items = dedupe_max(items)
        items = await self.reranker.rerank(query or "", items)
        return ContextPack(query=query, symbol=symbol, mode=mode, items=items, notes=notes)

    async def _expand(
        self,
        seeds: dict[str, float],
        kinds: list[EdgeKind],
        direction: Direction,
        depth: int,
        items: list[ContextItem],
        notes: list[str],
    ) -> None:
        cfg = self.config
        frontier = dict(seeds)
        visited = set(seeds)
        for hop in range(1, depth + 1):
            nxt: dict[str, float] = {}
            for sid, score in frontier.items():
                parent = await self.store.graph.get(sid)
                pname = parent.name if parent else sid
                edges = await self.store.graph.adjacent(sid, kinds, direction)
                if len(edges) > cfg.fanout_cap:
                    notes.append(f"fan-out cap {cfg.fanout_cap} at {pname} ({len(edges)} edges)")
                    edges = edges[: cfg.fanout_cap]
                for edge in edges:
                    other = edge.dst if edge.src == sid else edge.src
                    onode = await self.store.graph.get(other)
                    if onode is None:
                        continue
                    oscore = step_score(
                        score, cfg.decay, edge_weight(cfg.edge_weights, edge.provenance.source)
                    )
                    items.append(
                        self._item(onode, oscore, [f"{edge.kind.value} of {pname} (hop {hop})"])
                    )
                    if other not in visited:
                        visited.add(other)
                        nxt[other] = max(nxt.get(other, 0.0), oscore)
            frontier = nxt
            if not frontier:
                break

    def _item(self, node: Node, score: float, why: list[str]) -> ContextItem:
        return ContextItem(
            id=node.id,
            kind=node.kind,
            name=node.name,
            score=score,
            path=SymbolID.parse(node.id).path,
            span=node.span,
            code=node.attrs.get("code"),
            provenance=node.provenance.source,
            why=list(why),
        )

    def _filter(
        self,
        items: list[ContextItem],
        min_provenance: Literal["parsed", "resolved"] | None,
        include_llm_facts: bool,
    ) -> list[ContextItem]:
        floor = _FLOOR[min_provenance] if min_provenance else None
        out: list[ContextItem] = []
        for it in items:
            if not include_llm_facts and it.provenance is Source.LLM:
                continue
            if floor is not None and _RANK[it.provenance] < floor:
                continue
            out.append(it)
        return out
