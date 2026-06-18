"""``Retriever`` — vector entry → typed graph expansion → provenance-weighted
merge. Deterministic and LLM-free; the single retrieval surface feat-008 and
the enrichers ride on.
"""

from __future__ import annotations

from typing import Literal

from agentforge_graph.config import RetrieveConfig
from agentforge_graph.core import Direction, EdgeKind, Node, NodeKind, Source, SymbolID
from agentforge_graph.embed import Embedder
from agentforge_graph.store import Store

from .pack import ContextItem, ContextPack
from .rerank import NoopReranker, Reranker
from .scoring import dedupe_max, edge_weight, step_score

Mode = Literal["context", "impact", "definition", "similar"]

# code-symbol kinds an as_of allow-filter constrains (feat-009)
_SYMBOL_KINDS = frozenset({NodeKind.CLASS, NodeKind.FUNCTION, NodeKind.METHOD})

# Trust order for the min_provenance filter: llm < parsed < resolved <= manual
# (human-asserted facts are trusted; ADR-0004 / spec §2). Distinct from
# GraphQuery.min_source and from the scoring edge_weights.
_RANK: dict[Source, int] = {Source.LLM: 0, Source.PARSED: 1, Source.RESOLVED: 2, Source.MANUAL: 3}
_FLOOR: dict[str, int] = {"parsed": 1, "resolved": 2}

# feat-009 churn/authorship fields denormalised onto a symbol's node.attrs; the
# Retriever surfaces them on the item without joining the temporal sidecar (it
# stays in the deterministic core, ADR-0001). Empty → item.temporal stays None.
_TEMPORAL_KEYS = (
    "introduced",
    "introduced_ts",
    "last_changed",
    "last_changed_ts",
    "churn_30d",
    "churn_90d",
    "top_authors",
)


def _temporal_attrs(node: Node) -> dict[str, object] | None:
    out = {k: node.attrs[k] for k in _TEMPORAL_KEYS if k in node.attrs}
    return out or None


_MODE_EDGES: dict[Mode, tuple[list[EdgeKind], Direction]] = {
    # GOVERNS/DESCRIBES (feat-010) surface the decision/doc governing a retrieved
    # symbol; TAGGED + SUMMARIZES (feat-012) surface its design-pattern role and
    # the module summary. The differentiators; llm items obey include_llm_facts.
    "context": (
        [
            EdgeKind.CALLS,
            EdgeKind.CONTAINS,
            EdgeKind.INHERITS,
            EdgeKind.REFERENCES,
            EdgeKind.GOVERNS,
            EdgeKind.DESCRIBES,
            EdgeKind.TAGGED,
            EdgeKind.SUMMARIZES,
        ],
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
        allow_ids: set[str] | None = None,
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
                    # a chunk hit seeds its symbols; a summary hit (feat-012)
                    # seeds the code it summarizes — concept query → code.
                    for edge in await self.store.graph.adjacent(
                        hit.ref, [EdgeKind.CHUNK_OF, EdgeKind.SUMMARIZES], "out"
                    ):
                        seeds[edge.dst] = max(seeds.get(edge.dst, 0.0), hit.score)
                    # a doc-chunk hit (feat-010) seeds its containing Decision, which
                    # then expands via GOVERNS to the code it governs — so an
                    # architectural query surfaces the decision *and* the governed code.
                    if node.kind is NodeKind.DOC_CHUNK:
                        for edge in await self.store.graph.adjacent(
                            hit.ref, [EdgeKind.CONTAINS], "in"
                        ):
                            seeds[edge.src] = max(seeds.get(edge.src, 0.0), hit.score)
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
        if allow_ids is not None:  # feat-009 as_of: drop symbols not alive at the commit
            items = [it for it in items if it.kind not in _SYMBOL_KINDS or it.id in allow_ids]
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
            code=self._render_code(node),
            provenance=node.provenance.source,
            why=list(why),
            temporal=_temporal_attrs(node),
        )

    @staticmethod
    def _render_code(node: Node) -> str | None:
        """The verbatim block a retrieved item renders. A Decision (feat-010)
        shows its status/date inline so the agent sees governance at a glance."""
        if node.kind is NodeKind.DECISION:
            status = node.attrs.get("status", "")
            date = node.attrs.get("date", "")
            adr = node.attrs.get("adr_id", "")
            stamp = ", ".join(x for x in (status, date) if x)
            prefix = f"[{stamp}] " if stamp else ""
            label = f"{adr}: " if adr else ""
            return f"{prefix}{label}{node.attrs.get('title', node.name)}"
        if node.kind is NodeKind.PATTERN_TAG:
            return f"[llm] design pattern: {node.name}"
        if node.kind is NodeKind.SUMMARY:
            return f"[summary] {node.attrs.get('text', '')}"
        if node.kind is NodeKind.DOC_CHUNK:  # feat-010 — ADR/doc prose
            heading = node.attrs.get("heading", "")
            text = node.attrs.get("text", "")
            return f"[doc] {heading}\n{text}".strip() if heading else f"[doc] {text}".strip()
        return node.attrs.get("code")

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
