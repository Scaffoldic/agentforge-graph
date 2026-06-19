"""``IncrementalIndexer`` — apply a ``ChangeSet`` to an existing index.

Cost is proportional to the diff and its import-graph neighbourhood, not the
repo. The sequence (spec §4.3):

1. record the symbols about to disappear (for dirty propagation);
2. delete removed files (graph + vectors);
3. re-extract + upsert the touched files (scoped ``IngestPipeline``);
4. clear resolved edges in the re-resolve *scope* and re-resolve just that
   scope — ``scope = changed ∪ importers(changed)`` out to
   ``resolve_scope_hops`` import-graph hops;
5. append the dirtied symbols (changed + 1-hop neighbours) to the ``DirtySet``.

Correctness is asserted by the equivalence property test
(``refresh(diff) == full_reindex``); this module's scope heuristics are the
performance knob, the property test is the safety net.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from agentforge_graph.core import GraphQuery, Node, NodeKind, SymbolID
from agentforge_graph.frameworks import FrameworkExtractor
from agentforge_graph.store import Store

from ..pack import PackRegistry
from ..report import IndexReport
from ..resolver import ImportResolver
from ..source import RepoSource, read_go_module
from .detect import ChangeSet
from .dirty import DirtySet
from .ports import TemporalRecorder

_ALL = 10_000_000


class IncrementalIndexer:
    def __init__(
        self,
        store: Store,
        source: RepoSource,
        registry: PackRegistry,
        repo: str,
        commit: str = "",
        resolve_scope_hops: int = 1,
        dirty: DirtySet | None = None,
        frameworks: FrameworkExtractor | None = None,
        recorder: TemporalRecorder | None = None,
        commit_ts: int = 0,
    ) -> None:
        self.store = store
        self.source = source
        self.registry = registry
        self.repo = repo
        self.commit = commit
        self.resolve_scope_hops = resolve_scope_hops
        self.dirty = dirty
        self.frameworks = frameworks
        # feat-009: optional evolution-log recorder (None when temporal off).
        self.recorder = recorder
        self.commit_ts = commit_ts

    async def refresh(self, changes: ChangeSet) -> IndexReport:
        if changes.is_empty():
            return IndexReport()

        # avoid an import cycle (pipeline imports nothing incremental)
        from ..pipeline import IngestPipeline

        removed = changes.removed_paths()
        touched = set(changes.touched_paths())

        # (0) feat-009: snapshot the symbols of every file the diff touches
        # (removed + touched) *before* any mutation — diffing against the
        # post-upsert set yields exactly the opened/closed lifecycle events.
        before_symbols: set[str] = set()
        if self.recorder is not None:
            before_symbols = await self._symbols_in(sorted({*removed, *touched}))

        # (1) symbols that will vanish with the removed files — dirty them now
        dirty_ids: set[str] = await self._symbols_in(removed)

        # (2) delete removed files from both stores
        for path in removed:
            await self.store.graph.delete_file(path)
            await self.store.vectors.delete_where({"path": path})

        # (3) re-extract + upsert the touched files (resolve deferred to (4));
        # active framework packs re-emit their facts into the touched subgraphs.
        report = await IngestPipeline(self.repo, self.commit, frameworks=self.frameworks).run(
            self.source, self.store.graph, self.registry, paths=touched
        )

        # (4) scoped re-resolve: clear the scope's resolved edges, rebuild them
        scope = await self._resolve_scope(changes)
        await self.store.graph.clear_resolved(sorted(scope))
        stats = await ImportResolver(
            self.registry, self.commit, go_module=read_go_module(self.source.root)
        ).resolve(self.store.graph, changed_files=sorted(scope))
        report.resolve = stats
        imports = stats.imports_resolved + stats.imports_external
        report.by_edge_kind["IMPORTS"] = report.by_edge_kind.get("IMPORTS", 0) + imports
        report.by_edge_kind["CALLS"] = report.by_edge_kind.get("CALLS", 0) + stats.refs_resolved
        if stats.inherits_resolved:
            report.by_edge_kind["INHERITS"] = (
                report.by_edge_kind.get("INHERITS", 0) + stats.inherits_resolved
            )
        report.edges += imports + stats.refs_resolved + stats.inherits_resolved

        # feat-011 pass-2: ORM RELATES_TO is globally idempotent (clear all +
        # rebuild from the whole-repo model set), so a scoped refresh converges
        # to the same edges a full re-index would produce.
        if self.frameworks is not None and self.frameworks.active:
            resolved, unresolved = await self.frameworks.resolve(self.store.graph, self.commit)
            if resolved:
                report.relations_resolved = resolved
                report.by_edge_kind["RELATES_TO"] = (
                    report.by_edge_kind.get("RELATES_TO", 0) + resolved
                )
                report.edges += resolved
            report.framework_unresolved += unresolved

        # (5) dirty propagation: touched symbols + 1-hop neighbours of all dirty
        after_symbols = await self._symbols_in(sorted(touched))
        dirty_ids |= after_symbols
        dirty_ids |= await self._neighbours_of(dirty_ids)
        if self.dirty is not None:
            await self.dirty.add(sorted(dirty_ids))

        # (6) feat-009: record lifecycle. opened = now present, weren't before;
        # closed = were present, now gone (deleted files + symbols dropped from a
        # modified file). Written in one transaction at flush.
        if self.recorder is not None:
            self.recorder.open(sorted(after_symbols - before_symbols), self.commit, self.commit_ts)
            self.recorder.close(sorted(before_symbols - after_symbols), self.commit, self.commit_ts)
            # churn/authorship for the touched files → aggregates + denormalised
            # onto node attrs (feat-009 chunk 2).
            await self.recorder.record_churn(
                self.store.graph,
                str(self.source.root),
                sorted(touched),
                self.commit,
                self.commit_ts,
            )
            await self.recorder.flush()
        return report

    # --- helpers ----------------------------------------------------------

    async def _all_nodes(self) -> list[Node]:
        return (await self.store.graph.query(GraphQuery(limit=_ALL))).nodes

    async def _symbols_in(self, paths: list[str]) -> set[str]:
        """Code-symbol ids (Class/Function/Method) whose file is in ``paths``."""
        if not paths:
            return set()
        want = set(paths)
        kinds = {NodeKind.CLASS, NodeKind.FUNCTION, NodeKind.METHOD}
        return {
            n.id
            for n in await self._all_nodes()
            if n.kind in kinds and SymbolID.parse(n.id).path in want
        }

    async def _neighbours_of(self, ids: set[str]) -> set[str]:
        out: set[str] = set()
        for nid in ids:
            for nb in await self.store.graph.neighbors(nid, None, depth=1):
                out.add(nb.id)
        return out

    async def _resolve_scope(self, changes: ChangeSet) -> set[str]:
        """``changed ∪ importers(changed)`` out to ``resolve_scope_hops`` hops
        in the import graph. Importers are matched by *module key* (not by edge)
        so added, deleted and modified files are handled uniformly — an importer
        of an added file resolves to it now; an importer of a deleted file falls
        back to an external package, exactly as a full re-index would."""
        scope = set(changes.changed_paths())
        # per-file imports as module keys, read from the current graph
        file_imports = await self._file_import_keys()
        frontier = self._module_keys(scope)
        for _ in range(max(self.resolve_scope_hops, 0)):
            importers = {
                path for path, keys in file_imports.items() if keys & frontier and path not in scope
            }
            if not importers:
                break
            scope |= importers
            frontier = self._module_keys(importers)
        return scope

    async def _file_import_keys(self) -> dict[str, set[str]]:
        """For every FILE node, the set of module keys it imports (resolved the
        same way the resolver resolves them)."""
        out: dict[str, set[str]] = {}
        for n in await self._all_nodes():
            if n.kind is not NodeKind.FILE:
                continue
            path = SymbolID.parse(n.id).path
            pack = self.registry.for_extension(PurePosixPath(path).suffix)
            if pack is None:
                continue
            keys = {
                pack.resolve_import(path, imp.get("module", ""))
                for imp in n.attrs.get("imports", [])
                if imp.get("module")
            }
            out[path] = keys
        return out

    def _module_keys(self, paths: set[str]) -> set[str]:
        keys: set[str] = set()
        for path in paths:
            pack = self.registry.for_extension(PurePosixPath(path).suffix)
            if pack is not None:
                keys.add(pack.module_path(path))
        return keys
