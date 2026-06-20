"""Generic cross-file framework stitching (ENH-011) — pass-2.

The intra-file packs (feat-011) emit ``Route``/``Service`` nodes plus, in
pass-1, two cross-file facts: each route's ``router_var`` (the ``@app``/
``@router`` object it hangs off) and a ``RouteMount`` marker for every
``include_router(x.router, prefix="/api")`` / ``app.use('/api', router)`` /
``register_blueprint(bp, url_prefix=…)``. This module turns those facts into a
resolved graph, reading **only the persisted graph** — ``IMPORTS`` edges (built
by the language resolver) plus the nodes' own attrs. It never imports the
resolver internals, so the deterministic engine core stays untouched (ADR-0001).

Two stitches, both framework-agnostic (the shape is identical for FastAPI,
Flask and Express; only pass-1 capture differs per pack) and **globally
idempotent** — every run recomputes from scratch, so an incremental resolve
converges to the same graph as a full re-index (feat-004):

* **Route-prefix composition** — recompute every route's ``path_pattern`` from
  its immutable base ``path`` plus the prefix of the mount that includes its
  router. The base ``path`` is parsed ground truth and is never mutated.
* **DI grounding** — resolve a ``Service``'s provider *name* to the in-repo
  ``Function``/``Method``/``Class`` that defines it (via the consumer file's
  imports) and emit a traversable ``PROVIDED_BY`` edge.

Resolution is **unique-match-only** (ADR-0004): an ambiguous or external target
is left unresolved and counted, never guessed.
"""

from __future__ import annotations

from pydantic import BaseModel

from agentforge_graph.core import (
    Edge,
    EdgeKind,
    GraphQuery,
    GraphStore,
    Node,
    NodeKind,
    Provenance,
    SymbolID,
)

_ALL = 10_000_000  # effectively unbounded query for v0.1 graph sizes
_EXTRACTOR = "cross_file@1"


class CrossFileStats(BaseModel):
    """What pass-2 stitched this run (folded into the IndexReport)."""

    route_prefixes_composed: int = 0  # routes whose path_pattern gained a prefix
    di_providers_grounded: int = 0  # Service nodes grounded to a provider symbol
    unresolved: int = 0  # mounts / providers seen but ambiguous or external


def _file_id(node_id: str) -> str:
    """The FILE node id owning a symbol — same (lang, repo, path), empty
    descriptor (see ``extractor`` FILE-node construction)."""
    p = SymbolID.parse(node_id)
    return SymbolID.for_symbol(p.lang, p.repo, p.path, "")


def _join_path(prefix: str, path: str) -> str:
    """Compose a router prefix onto a route path: ``("/api", "/charge")`` →
    ``"/api/charge"``; an empty/root sub-path collapses to the prefix."""
    if not prefix:
        return path
    base = prefix.rstrip("/")
    rest = path.lstrip("/")
    return f"{base}/{rest}" if rest else base


def _module_segments(path: str) -> set[str]:
    """Names a dotted router ref's head could plausibly use to address the file
    that defines the router — the file stem and its parent directory. Used only
    to disambiguate when two imported files expose the same ``router_var``."""
    parts = path.replace("\\", "/").split("/")
    stem = parts[-1].rsplit(".", 1)[0]
    segs = {stem}
    if len(parts) >= 2:
        segs.add(parts[-2])
    return segs


class _CrossFileResolver:
    """Loads the framework-relevant slice of the graph once and runs both
    stitches against it, sharing the per-file ``IMPORTS`` cache."""

    def __init__(self, store: GraphStore, commit: str) -> None:
        self._store = store
        self._prov = Provenance.resolved(_EXTRACTOR, commit)
        self._file_ids: set[str] = set()
        self._imports: dict[str, set[str]] = {}

    async def _q(self, *kinds: NodeKind) -> list[Node]:
        return (await self._store.query(GraphQuery(kinds=list(kinds), limit=_ALL))).nodes

    async def _imported_files(self, file_id: str) -> set[str]:
        """In-repo files ``file_id`` imports (IMPORTS edges to FILE nodes)."""
        cached = self._imports.get(file_id)
        if cached is not None:
            return cached
        edges = await self._store.adjacent(file_id, [EdgeKind.IMPORTS], direction="out")
        targets = {e.dst for e in edges if e.dst in self._file_ids}
        self._imports[file_id] = targets
        return targets

    async def run(self) -> CrossFileStats:
        self._file_ids = {f.id for f in await self._q(NodeKind.FILE)}
        stats = CrossFileStats()
        await self._compose_route_prefixes(stats)
        await self._ground_di_providers(stats)
        return stats

    # --- route-prefix composition -------------------------------------------

    async def _compose_route_prefixes(self, stats: CrossFileStats) -> None:
        routes = await self._q(NodeKind.ROUTE)
        mounts = await self._q(NodeKind.ROUTE_MOUNT)
        routes_by_file: dict[str, list[Node]] = {}
        for r in routes:
            routes_by_file.setdefault(_file_id(r.id), []).append(r)

        # Per route, the prefix contributed by the (unique) mount that includes
        # its router. Conflicting prefixes on one route → ambiguous, left bare.
        prefix_of: dict[str, str] = {}
        conflict: set[str] = set()
        for m in mounts:
            applied = await self._mount_targets(m, routes_by_file)
            if applied is None:
                stats.unresolved += 1
                continue
            prefix = str(m.attrs.get("prefix", ""))
            if not prefix:
                continue
            for r in applied:
                if r.id in prefix_of and prefix_of[r.id] != prefix:
                    conflict.add(r.id)
                else:
                    prefix_of[r.id] = prefix

        for r in routes:
            base = str(r.attrs.get("path", ""))
            if r.id in conflict or r.id not in prefix_of:
                pattern = base
            else:
                pattern = _join_path(prefix_of[r.id], base)
            # Idempotent: set_attrs overwrites path_pattern every run from the
            # immutable base path, so incremental == full.
            await self._store.set_attrs(r.id, {"path_pattern": pattern})
            if pattern != base:
                stats.route_prefixes_composed += 1
        stats.unresolved += len(conflict)

    async def _mount_targets(
        self, mount: Node, routes_by_file: dict[str, list[Node]]
    ) -> list[Node] | None:
        """Routes a mount applies its prefix to: routes whose ``router_var``
        matches the included router, in a file the mounting file imports (or the
        mounting file itself, for a router declared and mounted in one module).
        Returns None when the target is ambiguous (multiple files expose the
        same router and the ref's head doesn't disambiguate)."""
        router_var = str(mount.attrs.get("router_var", ""))
        if not router_var:
            return None
        mount_file = _file_id(mount.id)
        scope = await self._imported_files(mount_file) | {mount_file}
        cands = [
            r
            for f in scope
            for r in routes_by_file.get(f, [])
            if str(r.attrs.get("router_var", "")) == router_var
        ]
        if not cands:
            return None
        files_hit = {_file_id(r.id) for r in cands}
        if len(files_hit) > 1:
            ref = str(mount.attrs.get("router_ref", ""))
            head = ref.split(".", 1)[0] if "." in ref else ""
            if not head:
                return None
            narrowed = {f for f in files_hit if head in _module_segments(SymbolID.parse(f).path)}
            if len(narrowed) != 1:
                return None
            cands = [r for r in cands if _file_id(r.id) in narrowed]
        return cands

    # --- DI grounding --------------------------------------------------------

    async def _ground_di_providers(self, stats: CrossFileStats) -> None:
        services = await self._q(NodeKind.SERVICE)
        if not services:
            return
        # Globally idempotent: drop the previous generation of PROVIDED_BY before
        # rebuilding, mirroring the ORM RELATES_TO clear-and-rebuild.
        await self._store.clear_outgoing([s.id for s in services], EdgeKind.PROVIDED_BY)

        defs = await self._q(NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.CLASS)
        by_file_name: dict[tuple[str, str], set[str]] = {}
        for d in defs:
            if d.name:
                by_file_name.setdefault((_file_id(d.id), d.name), set()).add(d.id)

        edges: list[Node | Edge] = []
        for s in services:
            provider = str(s.attrs.get("provider", ""))
            if not provider:
                stats.unresolved += 1
                continue
            consumer_file = _file_id(s.id)
            scope = await self._imported_files(consumer_file) | {consumer_file}
            cands: set[str] = set()
            for f in scope:
                cands |= by_file_name.get((f, provider), set())
            if len(cands) != 1:
                stats.unresolved += 1  # external or ambiguous provider
                continue
            target = next(iter(cands))
            edges.append(
                Edge(
                    src=s.id,
                    dst=target,
                    kind=EdgeKind.PROVIDED_BY,
                    provenance=self._prov,
                    origin_path=SymbolID.parse(s.id).path,
                )
            )
            await self._store.set_attrs(s.id, {"provider_symbol": target})
            stats.di_providers_grounded += 1
        if edges:
            await self._store.add(edges)


async def resolve_cross_file(store: GraphStore, commit: str = "") -> CrossFileStats:
    """Run both cross-file stitches and return what was resolved. Idempotent."""
    return await _CrossFileResolver(store, commit).run()
