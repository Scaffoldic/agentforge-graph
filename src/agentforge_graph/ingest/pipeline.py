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

from .extractor import TreeSitterExtractor
from .pack import LanguagePack, PackRegistry
from .report import IndexReport
from .resolver import ImportResolver
from .source import RepoSource


def _extract_one(pack: LanguagePack, repo: str, commit: str, sf: SourceFile) -> FileSubgraph:
    # Built and used entirely within the worker thread (parser is not shareable).
    return TreeSitterExtractor(pack, repo, commit).extract(sf)


class IngestPipeline:
    def __init__(self, repo: str, commit: str = "", concurrency: int = 8) -> None:
        self.repo = repo
        self.commit = commit
        self.concurrency = concurrency

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
        re-resolution. ``paths is None`` is the full-index path (resolve runs)."""
        report = IndexReport()
        sem = asyncio.Semaphore(self.concurrency)

        async def _do(sf: SourceFile) -> FileSubgraph | None:
            pack = registry.for_slug(sf.language)
            if pack is None:
                return None
            async with sem:
                sg = await asyncio.to_thread(_extract_one, pack, self.repo, self.commit, sf)
            await store.upsert(sg)
            return sg

        files = (sf for sf in source.iter_files(registry) if paths is None or sf.path in paths)
        subgraphs = await asyncio.gather(*[_do(sf) for sf in files])

        for sg in subgraphs:
            if sg is None:
                continue
            report.files_indexed += 1
            report.nodes += len(sg.nodes)
            report.edges += len(sg.edges)
            for n in sg.nodes:
                report.by_node_kind[n.kind.value] = report.by_node_kind.get(n.kind.value, 0) + 1
            for e in sg.edges:
                report.by_edge_kind[e.kind.value] = report.by_edge_kind.get(e.kind.value, 0) + 1
        report.skipped = list(source.skipped)

        if paths is not None:
            # Scoped (incremental) extract: the caller re-resolves with the
            # right import-graph scope. Edge tallies come from that pass.
            return report

        stats = await ImportResolver(registry, self.commit).resolve(store)
        report.resolve = stats
        imports = stats.imports_resolved + stats.imports_external
        report.by_edge_kind["IMPORTS"] = report.by_edge_kind.get("IMPORTS", 0) + imports
        report.by_edge_kind["CALLS"] = report.by_edge_kind.get("CALLS", 0) + stats.refs_resolved
        report.edges += imports + stats.refs_resolved
        return report
