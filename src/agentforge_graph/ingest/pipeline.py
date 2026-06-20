"""``IngestPipeline`` — drives the two passes over a whole repo.

Extraction is CPU-bound and file-isolated, so files are parsed on a thread
pool with bounded concurrency; the store serializes its own writes. A fresh
``TreeSitterExtractor`` is built inside each worker thread because a
tree-sitter ``Parser`` is not safe to share across threads (the grammar
itself is cached, so only the lightweight parser/query objects are rebuilt).
After all files are upserted, the resolver runs once.
"""

from __future__ import annotations

import asyncio

from agentforge_graph.core import FileSubgraph, GraphStore, SourceFile
from agentforge_graph.frameworks import FrameworkExtractor
from agentforge_graph.frameworks.extractor import FrameworkResolveStats

from .extractor import TreeSitterExtractor
from .pack import LanguagePack, PackRegistry
from .report import IndexReport
from .resolver import ImportResolver
from .source import RepoSource, read_go_module


def _apply_framework_resolve(report: IndexReport, fw: FrameworkResolveStats) -> None:
    """Fold a framework pass-2 result (ORM RELATES_TO + ENH-011 cross-file
    route-prefix / DI grounding) into the report. Shared by the full pipeline
    and the incremental indexer so both report identically."""
    if fw.relations_resolved:
        report.relations_resolved = fw.relations_resolved
        report.by_edge_kind["RELATES_TO"] = (
            report.by_edge_kind.get("RELATES_TO", 0) + fw.relations_resolved
        )
        report.edges += fw.relations_resolved
    if fw.route_prefixes_composed:
        report.route_prefixes_composed = fw.route_prefixes_composed
    if fw.di_providers_grounded:
        report.di_providers_grounded = fw.di_providers_grounded
        report.by_edge_kind["PROVIDED_BY"] = (
            report.by_edge_kind.get("PROVIDED_BY", 0) + fw.di_providers_grounded
        )
        report.edges += fw.di_providers_grounded
    if fw.route_handlers_grounded:
        report.route_handlers_grounded = fw.route_handlers_grounded
        report.by_edge_kind["HANDLED_BY"] = (
            report.by_edge_kind.get("HANDLED_BY", 0) + fw.route_handlers_grounded
        )
        report.edges += fw.route_handlers_grounded
    report.framework_unresolved += fw.unresolved


def _extract_one(
    pack: LanguagePack,
    repo: str,
    commit: str,
    sf: SourceFile,
    frameworks: FrameworkExtractor | None,
) -> tuple[FileSubgraph, int]:
    # Built and used entirely within the worker thread (parser is not shareable).
    sg = TreeSitterExtractor(pack, repo, commit).extract(sf)
    unresolved = 0
    if frameworks is not None and frameworks.active:
        facts = frameworks.extract(sf, repo, commit)  # feat-011: routes/etc.
        unresolved = facts.unresolved
        if facts.nodes or facts.edges:
            sg = sg.model_copy(
                update={"nodes": [*sg.nodes, *facts.nodes], "edges": [*sg.edges, *facts.edges]}
            )
    return sg, unresolved


class IngestPipeline:
    def __init__(
        self,
        repo: str,
        commit: str = "",
        concurrency: int = 8,
        frameworks: FrameworkExtractor | None = None,
    ) -> None:
        self.repo = repo
        self.commit = commit
        self.concurrency = concurrency
        self.frameworks = frameworks

    async def run(
        self,
        source: RepoSource,
        store: GraphStore,
        registry: PackRegistry,
        paths: set[str] | None = None,
    ) -> IndexReport:
        """Extract + upsert each file, then resolve. When ``paths`` is given,
        only those files are (re)extracted (feat-004 incremental scope); the
        resolver is **not** run here — incremental refresh owns scoped
        re-resolution. ``paths is None`` is the full-index path (resolve runs).
        Active framework packs (feat-011) emit extra nodes/edges merged into
        each file's subgraph, so they ride the same upsert + incrementality."""
        report = IndexReport()
        sem = asyncio.Semaphore(self.concurrency)

        async def _do(sf: SourceFile) -> tuple[FileSubgraph, int] | None:
            pack = registry.for_slug(sf.language)
            if pack is None:
                return None
            async with sem:
                result = await asyncio.to_thread(
                    _extract_one, pack, self.repo, self.commit, sf, self.frameworks
                )
            await store.upsert(result[0])
            return result

        files = (sf for sf in source.iter_files(registry) if paths is None or sf.path in paths)
        results = await asyncio.gather(*[_do(sf) for sf in files])

        for result in results:
            if result is None:
                continue
            sg, unresolved = result
            report.files_indexed += 1
            report.nodes += len(sg.nodes)
            report.edges += len(sg.edges)
            report.framework_unresolved += unresolved
            for n in sg.nodes:
                report.by_node_kind[n.kind.value] = report.by_node_kind.get(n.kind.value, 0) + 1
            for e in sg.edges:
                report.by_edge_kind[e.kind.value] = report.by_edge_kind.get(e.kind.value, 0) + 1
        report.skipped = list(source.skipped)
        report.routes_extracted = report.by_node_kind.get("Route", 0)
        report.models_extracted = report.by_node_kind.get("DataModel", 0)
        report.services_extracted = report.by_node_kind.get("Service", 0)

        if paths is not None:
            # Scoped (incremental) extract: the caller re-resolves with the
            # right import-graph scope. Edge tallies come from that pass.
            return report

        stats = await ImportResolver(
            registry, self.commit, go_module=read_go_module(source.root)
        ).resolve(store)
        report.resolve = stats
        imports = stats.imports_resolved + stats.imports_external
        report.by_edge_kind["IMPORTS"] = report.by_edge_kind.get("IMPORTS", 0) + imports
        report.by_edge_kind["CALLS"] = report.by_edge_kind.get("CALLS", 0) + stats.refs_resolved
        if stats.inherits_resolved:
            report.by_edge_kind["INHERITS"] = (
                report.by_edge_kind.get("INHERITS", 0) + stats.inherits_resolved
            )
        report.edges += imports + stats.refs_resolved + stats.inherits_resolved

        # feat-011 / ENH-011 pass-2: ORM RELATES_TO + cross-file route-prefix
        # composition and DI grounding.
        if self.frameworks is not None and self.frameworks.active:
            fw = await self.frameworks.resolve(store, self.commit)
            _apply_framework_resolve(report, fw)
        return report
