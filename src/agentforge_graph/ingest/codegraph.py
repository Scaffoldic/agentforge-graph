"""``CodeGraph`` — the top-level user facade (spec §4.1).

``index`` builds the embedded store (feat-003), runs the pipeline, and
returns a handle exposing the ``Store`` and the ``IndexReport``. ``open``
re-opens an existing index without re-indexing. This is the
``CodeGraph.open`` feat-003 deferred here (where ``index`` lives).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentforge_graph.store import Store

from .pack import PackRegistry
from .packs import BUILTIN_PACKS, builtin_registry
from .pipeline import IngestPipeline
from .report import IndexReport, RouteInfo
from .source import RepoSource

if TYPE_CHECKING:
    # embed/retrieve import ingest, so reference their types under TYPE_CHECKING.
    from agentforge_graph.embed import EmbedReport
    from agentforge_graph.repomap import RankedSymbol
    from agentforge_graph.retrieve import ContextPack
    from agentforge_graph.retrieve.retriever import Mode


def _git_commit(repo_path: str | Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def _framework_extractor(
    repo_path: str | Path, config: str | Path | None, registry: PackRegistry
) -> Any:
    """Detect the framework packs active for this repo (feat-011) and wrap them
    in a ``FrameworkExtractor``. Inactive (no framework / ``frameworks: off``)
    yields an empty extractor that the pipeline skips."""
    from agentforge_graph.frameworks import (
        FrameworkExtractor,
        active_frameworks,
        builtin_framework_registry,
    )

    exts = {ext for p in registry.packs for ext in p.extensions}
    packs = active_frameworks(repo_path, config, builtin_framework_registry(), exts)
    return FrameworkExtractor(packs)


def _save_meta(
    root: Path, commit: str, registry: PackRegistry, file_hashes: dict[str, str]
) -> None:
    """Persist the index manifest atomically, *last* — so a crash anywhere
    earlier leaves the previous consistent manifest and the next run re-derives
    the diff from it (feat-004)."""
    from .incremental import IndexMeta

    IndexMeta(
        indexed_commit=commit,
        pack_versions=IndexMeta.fingerprints(registry.packs),
        files=file_hashes,
    ).save(root)


def _registry_for(languages: str | list[str] | None) -> PackRegistry:
    if languages is None or languages == "auto":
        return builtin_registry()
    wanted = {languages} if isinstance(languages, str) else set(languages)
    packs = [p for p in BUILTIN_PACKS if p.language in wanted or p.lang_slug in wanted]
    return PackRegistry(packs)


def _source_registry(
    repo_path: str | Path,
    config: str | Path | None,
    languages: str | list[str] | None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> tuple[RepoSource, PackRegistry]:
    from agentforge_graph.config import IngestConfig

    ingest = IngestConfig.load(config)
    registry = _registry_for(languages if languages is not None else ingest.languages)
    source = RepoSource(
        repo_path,
        include=include,
        exclude=ingest.exclude + (exclude or []),
        max_file_kb=ingest.max_file_kb,
    )
    return source, registry


class CodeGraph:
    def __init__(
        self,
        store: Store,
        repo_path: str | Path = ".",
        config: str | Path | None = None,
        languages: str | list[str] | None = None,
        report: IndexReport | None = None,
    ) -> None:
        self._store = store
        self._repo_path = repo_path
        self._config = config
        self._languages = languages
        self._report = report
        self._embed_report: EmbedReport | None = None

    @classmethod
    async def index(
        cls,
        repo_path: str | Path = ".",
        languages: str | list[str] | None = None,
        config: str | Path | None = None,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        embed: bool = False,
        full: bool = False,
    ) -> CodeGraph:
        """Index ``repo_path``. Incremental by default once a prior index
        exists (feat-004) — only the diff is re-extracted/re-resolved. ``full``
        (or a changed pack fingerprint / schema bump / ``ingest.incremental:
        false``) forces a clean rebuild."""
        from agentforge_graph.config import IngestConfig, StoreConfig

        from .incremental import ChangeDetector, IndexMeta

        store = await Store.open(repo_path, config)
        source, registry = _source_registry(repo_path, config, languages, include, exclude)
        repo = Path(repo_path).resolve().name
        commit = _git_commit(repo_path)
        root = Path(repo_path) / StoreConfig.load(config).path
        ingest_cfg = IngestConfig.load(config)
        meta = IndexMeta.load(root)

        use_incremental = (
            ingest_cfg.incremental
            and not full
            and meta.is_indexed()
            and not meta.packs_changed(registry.packs)
        )
        cg = cls(store, repo_path, config, languages)
        frameworks = _framework_extractor(repo_path, config, registry)
        result = await ChangeDetector(repo_path).detect(source, meta, registry)
        if use_incremental:
            report = await cg._apply_changes(
                source,
                registry,
                repo,
                commit,
                result.changes,
                ingest_cfg.resolve_scope_hops,
                root,
                frameworks,
            )
        else:
            report = await IngestPipeline(repo=repo, commit=commit, frameworks=frameworks).run(
                source, store.graph, registry
            )
        cg._report = report
        _save_meta(root, commit, registry, result.file_hashes)
        if embed:
            await cg.embed()
        return cg

    async def refresh(self) -> IndexReport:
        """Re-index only what changed since the last index (feat-004). The
        explicit incremental entry point; ``index()`` calls the same path."""
        from agentforge_graph.config import IngestConfig, StoreConfig

        from .incremental import ChangeDetector, IndexMeta

        source, registry = _source_registry(self._repo_path, self._config, self._languages)
        repo = Path(self._repo_path).resolve().name
        commit = _git_commit(self._repo_path)
        root = Path(self._repo_path) / StoreConfig.load(self._config).path
        ingest_cfg = IngestConfig.load(self._config)
        meta = IndexMeta.load(root)
        frameworks = _framework_extractor(self._repo_path, self._config, registry)
        result = await ChangeDetector(self._repo_path).detect(source, meta, registry)
        report = await self._apply_changes(
            source,
            registry,
            repo,
            commit,
            result.changes,
            ingest_cfg.resolve_scope_hops,
            root,
            frameworks,
        )
        self._report = report
        _save_meta(root, commit, registry, result.file_hashes)
        return report

    async def _apply_changes(
        self,
        source: RepoSource,
        registry: PackRegistry,
        repo: str,
        commit: str,
        changes: object,
        resolve_scope_hops: int,
        root: Path,
        frameworks: Any = None,
    ) -> IndexReport:
        from .incremental import ChangeSet, DirtySet, IncrementalIndexer

        assert isinstance(changes, ChangeSet)
        indexer = IncrementalIndexer(
            self._store,
            source,
            registry,
            repo,
            commit,
            resolve_scope_hops=resolve_scope_hops,
            dirty=DirtySet(root),
            frameworks=frameworks,
        )
        return await indexer.refresh(changes)

    @classmethod
    async def open(
        cls,
        repo_path: str | Path = ".",
        config: str | Path | None = None,
        languages: str | list[str] | None = None,
    ) -> CodeGraph:
        return cls(await Store.open(repo_path, config), repo_path, config, languages)

    async def embed(self, embedder: object | None = None, only_dirty: bool = False) -> EmbedReport:
        """Chunk and embed everything indexed. Builds the embedder from
        ``EmbedConfig`` if not supplied. With ``only_dirty`` (feat-004), embed
        only the files a refresh dirtied for the ``embeddings`` consumer and
        mark them clean — the cheap path after an incremental index."""
        from agentforge_graph.chunking import CASTChunker
        from agentforge_graph.config import ChunkingConfig, EmbedConfig, StoreConfig
        from agentforge_graph.core import SymbolID
        from agentforge_graph.embed import Embedder, EmbedPipeline, embedder_from_config

        from .incremental import DirtySet

        chunking = ChunkingConfig.load(self._config)
        emb = (
            embedder
            if isinstance(embedder, Embedder)
            else embedder_from_config(EmbedConfig.load(self._config))
        )
        source, registry = _source_registry(self._repo_path, self._config, self._languages)
        pipeline = EmbedPipeline(
            CASTChunker(chunking.max_tokens, chunking.min_tokens),
            emb,
            commit=_git_commit(self._repo_path),
        )
        dirty: DirtySet | None = None
        only_paths: set[str] | None = None
        ids: list[str] = []
        if only_dirty:
            root = Path(self._repo_path) / StoreConfig.load(self._config).path
            dirty = DirtySet(root)
            ids = await dirty.dirty_for("embeddings")
            only_paths = {SymbolID.parse(i).path for i in ids}
        self._embed_report = await pipeline.run(
            self._store, source, registry, only_paths=only_paths
        )
        if dirty is not None:
            await dirty.mark_clean("embeddings", ids)
        return self._embed_report

    async def retrieve(
        self,
        query: str | None = None,
        symbol: str | None = None,
        mode: Mode = "context",
        k: int | None = None,
        depth: int | None = None,
        embedder: object | None = None,
    ) -> ContextPack:
        """Hybrid retrieval (feat-006): vector entry + graph expansion."""
        from agentforge_graph.config import EmbedConfig, RetrieveConfig
        from agentforge_graph.embed import Embedder, embedder_from_config
        from agentforge_graph.retrieve import Retriever

        emb = (
            embedder
            if isinstance(embedder, Embedder)
            else embedder_from_config(EmbedConfig.load(self._config))
        )
        retriever = Retriever(self._store, emb, RetrieveConfig.load(self._config))
        return await retriever.retrieve(query=query, symbol=symbol, mode=mode, k=k, depth=depth)

    async def repo_map(
        self,
        budget_tokens: int | None = None,
        focus: list[str] | None = None,
        scope: str | None = None,
    ) -> str:
        """Budget-aware, centrality-ranked repo map (feat-007)."""
        from agentforge_graph.config import RepoMapConfig
        from agentforge_graph.repomap import RepoMap

        rm = RepoMap(self._store, RepoMapConfig.load(self._config))
        return await rm.render(budget_tokens=budget_tokens, focus=focus, scope=scope)

    async def ranked_symbols(
        self, k: int = 100, focus: list[str] | None = None
    ) -> list[RankedSymbol]:
        from agentforge_graph.config import RepoMapConfig
        from agentforge_graph.repomap import RepoMap

        rm = RepoMap(self._store, RepoMapConfig.load(self._config))
        return await rm.ranked_symbols(k=k, focus=focus)

    async def routes(self) -> list[RouteInfo]:
        """Every extracted endpoint (feat-011): method, path pattern, handler
        symbol and source location, sorted by (path, method)."""
        from agentforge_graph.core import GraphQuery, NodeKind, SymbolID

        nodes = (
            await self._store.graph.query(GraphQuery(kinds=[NodeKind.ROUTE], limit=10_000_000))
        ).nodes
        routes = [
            RouteInfo(
                method=str(n.attrs.get("method", "")),
                path=str(n.attrs.get("path", "")),
                framework=str(n.attrs.get("framework", "")),
                handler=str(n.attrs.get("handler", "")),
                file=SymbolID.parse(n.id).path,
                line=n.span[0] if n.span else 0,
            )
            for n in nodes
        ]
        routes.sort(key=lambda r: (r.path, r.method))
        return routes

    @property
    def store(self) -> Store:
        return self._store

    def stats(self) -> IndexReport:
        if self._report is None:
            raise RuntimeError("no index report: open() does not index — use index()")
        return self._report

    def embed_stats(self) -> EmbedReport:
        if self._embed_report is None:
            raise RuntimeError("no embed report: call embed() first")
        return self._embed_report

    async def close(self) -> None:
        await self._store.close()
