"""``FrameworkExtractor`` — run the active framework packs over one file
(feat-011). Selects packs by the file's language and merges their
``FrameworkFacts``. File-isolated and stateless, so it runs inside the same
worker thread as the language extractor (pipeline)."""

from __future__ import annotations

from pydantic import BaseModel

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
from .cross_file import resolve_cross_file

_ALL = 10_000_000  # effectively unbounded query for v0.1 graph sizes


class FrameworkResolveStats(BaseModel):
    """What the framework pass-2 stitched this run (folded into the
    IndexReport). Combines the per-pack ORM ``RELATES_TO`` stitch with the
    generic cross-file route-prefix / DI grounding (ENH-011)."""

    relations_resolved: int = 0  # ORM RELATES_TO edges
    route_prefixes_composed: int = 0  # ENH-011 routes with a composed path_pattern
    di_providers_grounded: int = 0  # ENH-011 PROVIDED_BY edges
    route_handlers_grounded: int = 0  # ENH-012 cross-file HANDLED_BY (Laravel/Rails)
    unresolved: int = 0  # targets seen but ambiguous or external


class FrameworkExtractor:
    def __init__(self, packs: list[FrameworkPack]) -> None:
        self._packs = list(packs)
        self._by_slug: dict[str, list[FrameworkPack]] = {}
        for pack in packs:
            for slug in pack.slugs:
                self._by_slug.setdefault(slug, []).append(pack)

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

    async def resolve(self, store: GraphStore, commit: str = "") -> FrameworkResolveStats:
        """Run the framework pass-2 and replace the previous generation of
        framework-resolved facts. Globally idempotent — clears the prior
        ``RELATES_TO``/``PROVIDED_BY`` generation and recomputes every route's
        ``path_pattern`` from scratch, so an incremental resolve converges to the
        same graph as a full re-index (feat-004). Two stages:

        1. Per-pack ORM ``RELATES_TO`` (relationship/FK string targets).
        2. Generic cross-file route-prefix composition + DI grounding (ENH-011,
           ``cross_file``) — framework-agnostic, reads only the persisted graph.
        """
        if not self._packs:
            return FrameworkResolveStats()
        models = (await store.query(GraphQuery(kinds=[NodeKind.DATA_MODEL], limit=_ALL))).nodes
        if models:
            await store.clear_outgoing([m.id for m in models], EdgeKind.RELATES_TO)
        pending = sum(len(m.attrs.get("relations") or []) for m in models)

        edges: list[Node | Edge] = []
        for pack in self._packs:
            edges.extend(await pack.resolve(store, commit))
        if edges:
            await store.add(edges)

        cf = await resolve_cross_file(store, commit)
        return FrameworkResolveStats(
            relations_resolved=len(edges),
            route_prefixes_composed=cf.route_prefixes_composed,
            di_providers_grounded=cf.di_providers_grounded,
            route_handlers_grounded=cf.route_handlers_grounded,
            unresolved=max(0, pending - len(edges)) + cf.unresolved,
        )
