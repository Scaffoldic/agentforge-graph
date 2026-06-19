"""``FrameworkExtractor`` — run the active framework packs over one file
(feat-011). Selects packs by the file's language and merges their
``FrameworkFacts``. File-isolated and stateless, so it runs inside the same
worker thread as the language extractor (pipeline)."""

from __future__ import annotations

from agentforge_graph.core import (
    Edge,
    EdgeKind,
    GraphQuery,
    GraphStore,
    Node,
    NodeKind,
    SourceFile,
)

from .base import FrameworkFacts, FrameworkPack

_ALL = 10_000_000  # effectively unbounded query for v0.1 graph sizes


class FrameworkExtractor:
    def __init__(self, packs: list[FrameworkPack]) -> None:
        self._packs = list(packs)
        self._by_slug: dict[str, list[FrameworkPack]] = {}
        for pack in packs:
            self._by_slug.setdefault(pack.language_slug, []).append(pack)

    @property
    def active(self) -> bool:
        return bool(self._packs)

    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        merged = FrameworkFacts()
        for pack in self._by_slug.get(file.language, []):
            facts = pack.extract(file, repo, commit)
            merged.nodes.extend(facts.nodes)
            merged.edges.extend(facts.edges)
            merged.unresolved += facts.unresolved
        return merged

    async def resolve(self, store: GraphStore, commit: str = "") -> tuple[int, int]:
        """Run every active pack's cross-file pass-2 (ORM relationship/FK string
        targets, …) and replace the previous generation of framework-resolved
        edges. Globally idempotent: clears all ``RELATES_TO`` out of the current
        framework nodes, then rebuilds from the whole-repo node set — so an
        incremental resolve converges to the same graph as a full re-index
        (feat-004). Returns ``(edges_resolved, targets_unresolved)``."""
        if not self._packs:
            return 0, 0
        models = (await store.query(GraphQuery(kinds=[NodeKind.DATA_MODEL], limit=_ALL))).nodes
        if models:
            await store.clear_outgoing([m.id for m in models], EdgeKind.RELATES_TO)
        pending = sum(len(m.attrs.get("relations") or []) for m in models)

        edges: list[Node | Edge] = []
        for pack in self._packs:
            edges.extend(await pack.resolve(store, commit))
        if edges:
            await store.add(edges)
        return len(edges), max(0, pending - len(edges))
