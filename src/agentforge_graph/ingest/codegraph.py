"""``CodeGraph`` — the top-level user facade (spec §4.1).

``index`` builds the embedded store (feat-003), runs the pipeline, and
returns a handle exposing the ``Store`` and the ``IndexReport``. ``open``
re-opens an existing index without re-indexing. This is the
``CodeGraph.open`` feat-003 deferred here (where ``index`` lives).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentforge_graph.store import Store, resolve_root

from .pack import PackRegistry
from .packs import BUILTIN_PACKS, builtin_registry
from .pipeline import IngestPipeline
from .report import IndexReport, ModelInfo, RouteInfo, ServiceCallInfo, ServiceInfo
from .source import RepoSource

if TYPE_CHECKING:
    from agentforge_graph.config import ConfigSource

    # embed/retrieve import ingest, so reference their types under TYPE_CHECKING.
    from agentforge_graph.embed import EmbedReport
    from agentforge_graph.enrich import SummaryInfo, TaggedInfo
    from agentforge_graph.knowledge import DecisionInfo
    from agentforge_graph.repomap import RankedSymbol
    from agentforge_graph.retrieve import ContextPack
    from agentforge_graph.retrieve.retriever import Mode
    from agentforge_graph.store.query import QuerySettings, ResultTable, SchemaDescription

logger = logging.getLogger(__name__)


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


def _commit_time(repo_path: str | Path, commit: str) -> int:
    """Author time (epoch seconds) of ``commit`` — the timestamp stamped on
    feat-009 events. 0 if non-git / unknown."""
    if not commit:
        return 0
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_path), "show", "-s", "--format=%ct", commit],
            capture_output=True,
            text=True,
            check=True,
        )
        return int(out.stdout.strip() or 0)
    except (subprocess.SubprocessError, OSError, ValueError):
        return 0


def _build_recorder(repo_path: str | Path, config: ConfigSource, root: Path, commit: str):  # type: ignore[no-untyped-def]
    """Build the feat-009 evolution-log recorder when ``temporal.enabled`` and
    the source is a git repo; else ``None``. Lazy-imports ``temporal`` so the
    module is never loaded when the feature is off."""
    from agentforge_graph.config import TemporalConfig

    if not commit or not TemporalConfig.load(config).enabled:
        return None
    from agentforge_graph.temporal import build_recorder

    return build_recorder(str(root))


async def _prune_temporal(repo_path: str | Path, config: ConfigSource, root: Path) -> None:
    """Retention pruning (feat-009 §4.10): drop CLOSED events older than the
    ``retention_commits`` horizon at the end of an index/refresh. No-op when
    temporal is off, no sidecar exists, or history is shorter than the horizon."""
    from agentforge_graph.config import TemporalConfig

    cfg = TemporalConfig.load(config)
    if not cfg.enabled or not (root / "temporal.db").exists():
        return
    horizon = _commit_time(repo_path, f"HEAD~{cfg.retention_commits}")
    if horizon <= 0:  # fewer than retention_commits commits → nothing to prune
        return
    from agentforge_graph.temporal import TemporalStore

    await TemporalStore.open(root).prune(horizon)


def _framework_extractor(
    repo_path: str | Path, config: ConfigSource, registry: PackRegistry
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


async def _ingest_knowledge(
    store: Store,
    repo_path: str | Path,
    config: ConfigSource,
    repo: str,
    commit: str,
    registry: PackRegistry,
    report: IndexReport,
) -> None:
    """Run the ADR/knowledge pass (feat-010) after code indexing, so mention
    linking sees current code. No-op when ``knowledge.enabled`` is false."""
    from agentforge_graph.config import KnowledgeConfig
    from agentforge_graph.knowledge import CommitIngestor, KnowledgeIngestor

    cfg = KnowledgeConfig.load(config)
    if not cfg.enabled:
        return
    exts = {ext for p in registry.packs for ext in p.extensions}
    stats = await KnowledgeIngestor(repo, commit).ingest(
        store.graph, repo_path, cfg.adr_globs, exts, doc_globs=cfg.doc_globs
    )
    report.decisions_indexed = stats.decisions_indexed
    report.governs_resolved = stats.governs_resolved
    report.mentions_unresolved = stats.mentions_unresolved
    report.docs_indexed = stats.docs_indexed
    report.describes_resolved = stats.describes_resolved
    if cfg.commit_messages:
        report.commits_indexed = await CommitIngestor(
            repo, repo_path, commit, limit=cfg.commit_messages_limit
        ).ingest(store.graph)
    if stats.decisions_indexed:
        report.by_node_kind["Decision"] = (
            report.by_node_kind.get("Decision", 0) + stats.decisions_indexed
        )


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
    config: ConfigSource,
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
        config: ConfigSource = None,
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
        config: ConfigSource = None,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        embed: bool = False,
        full: bool = False,
    ) -> CodeGraph:
        """Index ``repo_path``. Incremental by default once a prior index
        exists (feat-004) — only the diff is re-extracted/re-resolved. ``full``
        (or a changed pack fingerprint / schema bump / ``ingest.incremental:
        false``) forces a clean rebuild."""
        from agentforge_graph.config import IngestConfig, StoreConfig, resolve_config
        from agentforge_graph.observability import configure_from_config

        from .incremental import ChangeDetector, IndexMeta

        config = resolve_config(config, repo_path)  # discover agentforge.yaml app: / ckg.yaml
        configure_from_config(config)  # honor logging.level for in-process consumers
        store = await Store.open(repo_path, config)
        source, registry = _source_registry(repo_path, config, languages, include, exclude)
        repo = Path(repo_path).resolve().name
        commit = _git_commit(repo_path)
        root = resolve_root(repo_path, StoreConfig.load(config))
        ingest_cfg = IngestConfig.load(config)
        meta = IndexMeta.load(root)

        use_incremental = (
            ingest_cfg.incremental
            and not full
            and meta.is_indexed()
            and not meta.packs_changed(registry.packs)
        )
        logger.info(
            "index: %s (commit %s) — %s",
            repo,
            (commit or "no-git")[:10],
            "incremental" if use_incremental else "full",
        )
        logger.debug("index: store=%s packs=%s", root, [p.lang_slug for p in registry.packs])
        cg = cls(store, repo_path, config, languages)
        frameworks = _framework_extractor(repo_path, config, registry)
        recorder = _build_recorder(repo_path, config, root, commit)  # feat-009 (None if off)
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
                recorder,
                _commit_time(repo_path, commit),
            )
        else:
            report = await IngestPipeline(repo=repo, commit=commit, frameworks=frameworks).run(
                source, store.graph, registry
            )
            if recorder is not None:  # full index: open intervals for all symbols
                from agentforge_graph.temporal import seed_symbols

                await seed_symbols(
                    store.graph,
                    recorder,
                    commit,
                    _commit_time(repo_path, commit),
                    repo_root=str(repo_path),
                )
        cg._report = report
        await _ingest_knowledge(store, repo_path, config, repo, commit, registry, report)
        _save_meta(root, commit, registry, result.file_hashes)
        await _prune_temporal(repo_path, config, root)
        logger.info(
            "index: %s done — %d files, %d nodes, %d edges",
            repo,
            report.files_indexed,
            report.nodes,
            report.edges,
        )
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
        root = resolve_root(self._repo_path, StoreConfig.load(self._config))
        ingest_cfg = IngestConfig.load(self._config)
        meta = IndexMeta.load(root)
        frameworks = _framework_extractor(self._repo_path, self._config, registry)
        recorder = _build_recorder(self._repo_path, self._config, root, commit)  # feat-009
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
            recorder,
            _commit_time(self._repo_path, commit),
        )
        self._report = report
        await _ingest_knowledge(
            self._store, self._repo_path, self._config, repo, commit, registry, report
        )
        _save_meta(root, commit, registry, result.file_hashes)
        await _prune_temporal(self._repo_path, self._config, root)
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
        recorder: Any = None,
        commit_ts: int = 0,
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
            recorder=recorder,
            commit_ts=commit_ts,
        )
        return await indexer.refresh(changes)

    @classmethod
    async def open(
        cls,
        repo_path: str | Path = ".",
        config: ConfigSource = None,
        languages: str | list[str] | None = None,
    ) -> CodeGraph:
        from agentforge_graph.config import resolve_config
        from agentforge_graph.observability import configure_from_config

        config = resolve_config(config, repo_path)  # discover agentforge.yaml app: / ckg.yaml
        configure_from_config(config)  # honor logging.level for in-process consumers
        logger.debug("open: %s", repo_path)
        return cls(await Store.open(repo_path, config), repo_path, config, languages)

    async def embed(self, embedder: object | None = None, only_dirty: bool = False) -> EmbedReport:
        """Chunk and embed everything indexed. Builds the embedder from
        ``EmbedConfig`` if not supplied. With ``only_dirty`` (feat-004), embed
        only the files a refresh dirtied for the ``embeddings`` consumer and
        mark them clean — the cheap path after an incremental index."""
        from agentforge_graph.chunking import CASTChunker
        from agentforge_graph.config import ChunkingConfig, EmbedConfig, StoreConfig
        from agentforge_graph.core import SymbolID
        from agentforge_graph.embed import (
            Embedder,
            EmbedPipeline,
            EmbedReport,
            embedder_from_config,
        )

        from .incremental import DirtySet

        chunking = ChunkingConfig.load(self._config)
        embed_cfg = EmbedConfig.load(self._config)
        # ENH-023: a repo with embed disabled builds no vectors — skip without
        # constructing an embedder (so no creds are required). An explicitly
        # supplied embedder is an intentional override and still runs.
        if not embed_cfg.enabled and not isinstance(embedder, Embedder):
            logger.info("embed: skipped (embed.enabled is false) — no vectors built")
            self._embed_report = EmbedReport(disabled=True)
            return self._embed_report
        emb = embedder if isinstance(embedder, Embedder) else embedder_from_config(embed_cfg)
        logger.info(
            "embed: %s via %s (dim %d)%s",
            Path(self._repo_path).resolve().name,
            emb.name,
            emb.dim,
            " [only dirty]" if only_dirty else "",
        )
        source, registry = _source_registry(self._repo_path, self._config, self._languages)
        pipeline = EmbedPipeline(
            CASTChunker(chunking.max_tokens, chunking.min_tokens),
            emb,
            commit=_git_commit(self._repo_path),
        )
        root = resolve_root(self._repo_path, StoreConfig.load(self._config))
        dirty: DirtySet | None = None
        only_paths: set[str] | None = None
        ids: list[str] = []
        if only_dirty:
            dirty = DirtySet(root)
            ids = await dirty.dirty_for("embeddings")
            only_paths = {SymbolID.parse(i).path for i in ids}
        self._embed_report = await pipeline.run(
            self._store, source, registry, only_paths=only_paths, doc_root=root
        )
        if dirty is not None:
            await dirty.mark_clean("embeddings", ids)
        r = self._embed_report
        logger.info(
            "embed: done — %d chunks across %d files (%d unchanged)%s",
            r.embedded,
            r.files,
            r.skipped_unchanged,
            f", {r.doc_chunks} doc chunks" if r.doc_chunks else "",
        )
        return self._embed_report

    async def retrieve(
        self,
        query: str | None = None,
        symbol: str | None = None,
        mode: Mode = "context",
        k: int | None = None,
        depth: int | None = None,
        embedder: object | None = None,
        include_llm_facts: bool = True,
        as_of: str | None = None,
    ) -> ContextPack:
        """Hybrid retrieval (feat-006): vector entry + graph expansion.
        ``include_llm_facts=False`` excludes llm-derived items (decisions tags
        etc.) wholesale (feat-010/012). ``as_of=<commit>`` (feat-009) restricts
        results to the symbols valid at that commit — code symbols added after it
        are dropped; raises ``TemporalError`` with no temporal data or beyond the
        retention horizon."""
        from agentforge_graph.config import EmbedConfig, RetrieveConfig
        from agentforge_graph.embed import Embedder, embedder_from_config
        from agentforge_graph.retrieve import Retriever
        from agentforge_graph.retrieve.rerank import reranker_from_config

        allow_ids: set[str] | None = None
        if as_of is not None:
            from agentforge_graph.temporal import TemporalError

            ti = self._temporal_index()
            if ti is None:
                raise TemporalError("as_of requested but no temporal log exists")
            allow_ids = await ti.alive_at(as_of)

        emb = (
            embedder
            if isinstance(embedder, Embedder)
            else embedder_from_config(EmbedConfig.load(self._config))
        )
        rcfg = RetrieveConfig.load(self._config)
        retriever = Retriever(
            self._store,
            emb,
            rcfg,
            reranker=reranker_from_config(
                rcfg.rerank, rcfg.rerank_weight, rcfg.rerank_model, rcfg.rerank_region
            ),
        )
        return await retriever.retrieve(
            query=query,
            symbol=symbol,
            mode=mode,
            k=k,
            depth=depth,
            include_llm_facts=include_llm_facts,
            allow_ids=allow_ids,
        )

    async def query_graph(
        self, text: str, settings: QuerySettings | None = None
    ) -> ResultTable:
        """Execute a read-only structural query (feat-015). ``settings`` bounds
        the run (row cap / timeout / expansions); defaults are used if omitted.
        Raises ``QueryError`` on bad input, ``QueryDisabled`` on a non-query
        backend."""
        from agentforge_graph.store.query import QuerySettings as _QuerySettings

        return await self._store.query_graph(text, settings or _QuerySettings())

    def describe_schema(self) -> SchemaDescription:
        """The queryable vocabulary (node/edge kinds + properties) for
        ``ckg query --schema`` (feat-015). Pure — needs no index."""
        from agentforge_graph.store.query import describe_schema

        return describe_schema()

    @property
    def query_enabled(self) -> bool:
        """True if the active backend can execute structural queries (feat-015)."""
        return self._store.query_enabled

    @property
    def query_capabilities(self) -> frozenset[str]:
        """Capability tiers the active backend executes (feat-015)."""
        return self._store.query_capabilities

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
                # ENH-011: the cross-file composed path; fall back to the base
                # path for routes indexed before path_pattern existed.
                path_pattern=str(n.attrs.get("path_pattern") or n.attrs.get("path", "")),
                framework=str(n.attrs.get("framework", "")),
                handler=str(n.attrs.get("handler", "")),
                file=SymbolID.parse(n.id).path,
                line=n.span[0] if n.span else 0,
            )
            for n in nodes
        ]
        routes.sort(key=lambda r: (r.path_pattern, r.method))
        return routes

    async def service_calls(self) -> list[ServiceCallInfo]:
        """Every outbound HTTP client call (ENH-020 C-full): method, URL, path,
        client library and source location, sorted by (path, method). The caller
        side of a cross-service edge — matched to routes at federation time."""
        from agentforge_graph.core import GraphQuery, NodeKind, SymbolID

        nodes = (
            await self._store.graph.query(
                GraphQuery(kinds=[NodeKind.SERVICE_CALL], limit=10_000_000)
            )
        ).nodes
        calls = [
            ServiceCallInfo(
                method=str(n.attrs.get("method", "")),
                url=str(n.attrs.get("url", "")),
                path=str(n.attrs.get("path", "")),
                framework=str(n.attrs.get("framework", "")),
                file=SymbolID.parse(n.id).path,
                line=n.span[0] if n.span else 0,
            )
            for n in nodes
        ]
        calls.sort(key=lambda c: (c.path, c.method))
        return calls

    async def models(self) -> list[ModelInfo]:
        """Every extracted ORM data model (feat-011): table, framework, mapped
        field names, ``RELATES_TO`` relations (FK / relationship), the underlying
        class symbol and source location, sorted by name."""
        from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID

        nodes = (
            await self._store.graph.query(GraphQuery(kinds=[NodeKind.DATA_MODEL], limit=10_000_000))
        ).nodes
        name_of = {n.id: str(n.attrs.get("table") or n.name) for n in nodes}
        models: list[ModelInfo] = []
        for n in nodes:
            fields = await self._store.graph.neighbors(n.id, [EdgeKind.HAS_FIELD], depth=1)
            field_names = sorted(f.name for f in fields if f.kind is NodeKind.VARIABLE and f.name)
            rel_edges = await self._store.graph.adjacent(
                n.id, [EdgeKind.RELATES_TO], direction="out"
            )
            relations = sorted(
                (
                    {
                        "to": name_of.get(e.dst, e.dst),
                        "kind": str(e.attrs.get("kind", "")),
                        "via": str(e.attrs.get("via", "")),
                    }
                    for e in rel_edges
                ),
                key=lambda r: (r["to"], r["via"]),
            )
            models.append(
                ModelInfo(
                    name=str(n.attrs.get("table") or n.name),
                    table=str(n.attrs.get("table", "")),
                    framework=str(n.attrs.get("framework", "")),
                    fields=field_names,
                    relations=relations,
                    cls=str(n.attrs.get("class", "")),
                    file=SymbolID.parse(n.id).path,
                    line=n.span[0] if n.span else 0,
                )
            )
        models.sort(key=lambda m: m.name)
        return models

    async def services(self) -> list[ServiceInfo]:
        """Every DI-provided service (feat-011): provider name, framework, the
        consumer symbols it is ``INJECTED_INTO``, and source location, sorted by
        name."""
        from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID

        nodes = (
            await self._store.graph.query(GraphQuery(kinds=[NodeKind.SERVICE], limit=10_000_000))
        ).nodes
        services: list[ServiceInfo] = []
        for n in nodes:
            edges = await self._store.graph.adjacent(
                n.id, [EdgeKind.INJECTED_INTO], direction="out"
            )
            services.append(
                ServiceInfo(
                    name=str(n.attrs.get("provider") or n.name),
                    framework=str(n.attrs.get("framework", "")),
                    injected_into=sorted(e.dst for e in edges),
                    file=SymbolID.parse(n.id).path,
                    line=n.span[0] if n.span else 0,
                )
            )
        services.sort(key=lambda s: s.name)
        return services

    def _temporal_index(self) -> Any:
        """A ``TemporalIndex`` over the sidecar, or ``None`` when the evolution
        log is absent (temporal never enabled / no git). Lazy-imports the
        higher temporal layer (ADR-0001)."""
        from agentforge_graph.config import StoreConfig, TemporalConfig

        root = resolve_root(self._repo_path, StoreConfig.load(self._config))
        if not (root / "temporal.db").exists():
            return None
        from agentforge_graph.temporal import TemporalIndex, TemporalStore

        return TemporalIndex(
            TemporalStore.open(root),
            self._store.graph,
            repo_root=str(self._repo_path),
            retention_commits=TemporalConfig.load(self._config).retention_commits,
        )

    async def history(self, symbol_id: str) -> Any:
        """A symbol's evolution (feat-009): introduced / last-changed / churn /
        authors / lifecycle events. ``None`` if the temporal layer has no data."""
        ti = self._temporal_index()
        return await ti.history(symbol_id) if ti is not None else None

    async def changed_since(self, ref: str, scope: str | None = None) -> list[Any]:
        """Symbols changed since ``ref`` (feat-009), newest first, optionally
        filtered to a path glob/prefix ``scope``. Empty if no temporal data."""
        ti = self._temporal_index()
        return await ti.changed_since(ref, scope) if ti is not None else []

    async def backfill(self, history: int) -> Any:
        """Seed the evolution log from git history (feat-009 chunk 4):
        ``history`` commits replayed into the temporal sidecar. Returns a
        ``BackfillReport``; a no-op (``ran=False``) when temporal is off, the
        range is already covered, or it isn't a git repo."""
        from agentforge_graph.temporal.backfill import run_backfill

        return await run_backfill(self._repo_path, self._config, history, languages=self._languages)

    async def temporal_status(self) -> dict[str, Any]:
        """Temporal sidecar summary for ``ckg status``: whether the feature is
        enabled, how many events the log holds, and how far back history has
        been backfilled."""
        from agentforge_graph.config import StoreConfig, TemporalConfig

        enabled = TemporalConfig.load(self._config).enabled
        root = resolve_root(self._repo_path, StoreConfig.load(self._config))
        db = root / "temporal.db"
        if not db.exists():
            return {"enabled": enabled, "events": 0, "has_sidecar": False, "backfilled_through": ""}
        from agentforge_graph.temporal import TemporalStore

        store = TemporalStore.open(root)
        return {
            "enabled": enabled,
            "events": await store.count_events(),
            "has_sidecar": True,
            "backfilled_through": await store.get_meta("backfilled_through") or "",
        }

    async def decisions(
        self, scope: str | None = None, status: str | None = None
    ) -> list[DecisionInfo]:
        """Architecture decisions (feat-010). ``scope`` keeps a decision whose
        own path is under the prefix or which governs a symbol under it;
        ``status`` filters by ADR status. Sorted by (status, date desc)."""
        from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
        from agentforge_graph.knowledge import DecisionInfo

        nodes = (
            await self._store.graph.query(GraphQuery(kinds=[NodeKind.DECISION], limit=10_000_000))
        ).nodes
        out: list[DecisionInfo] = []
        for n in nodes:
            governs = [
                e.dst for e in await self._store.graph.adjacent(n.id, [EdgeKind.GOVERNS], "out")
            ]
            if status and str(n.attrs.get("status", "")) != status:
                continue
            if scope:
                own = SymbolID.parse(n.id).path
                if not own.startswith(scope) and not any(
                    SymbolID.parse(g).path.startswith(scope) for g in governs
                ):
                    continue
            out.append(
                DecisionInfo(
                    id=n.id,
                    adr_id=str(n.attrs.get("adr_id", "")),
                    title=str(n.attrs.get("title", n.name)),
                    status=str(n.attrs.get("status", "")),
                    date=str(n.attrs.get("date", "")),
                    path=str(n.attrs.get("path", SymbolID.parse(n.id).path)),
                    governs=governs,
                )
            )
        out.sort(key=lambda d: (d.status, d.date), reverse=True)
        return out

    async def enrich(self, judge: object | None = None, budget_usd: float | None = None) -> Any:
        """LLM pattern enrichment (feat-012). Drains the ``patterns`` DirtySet
        if non-empty (incremental), else tags all Class/Function symbols. Builds
        the Bedrock judge from ``EnrichConfig`` unless one is supplied. Returns
        an ``EnrichReport``. Never runs implicitly — explicit call only."""
        from agentforge_graph.config import EnrichConfig, StoreConfig
        from agentforge_graph.core import GraphQuery
        from agentforge_graph.enrich import PatternHeuristics, PatternJudge, PatternTagEnricher
        from agentforge_graph.enrich.heuristics import Recall, class_and_function_ids

        from .incremental import DirtySet

        cfg = EnrichConfig.load(self._config)
        repo = Path(self._repo_path).resolve().name
        root = resolve_root(self._repo_path, StoreConfig.load(self._config))
        if isinstance(judge, PatternJudge):
            the_judge: PatternJudge = judge
        else:
            from agentforge_graph.enrich.registry import judge_from_config

            the_judge = judge_from_config(cfg)  # ENH-003: provider-selected

        dirty = DirtySet(root)
        dirty_ids = await dirty.dirty_for("patterns")
        if dirty_ids:
            symbol_ids = dirty_ids
        else:
            nodes = (await self._store.graph.query(GraphQuery(limit=10_000_000))).nodes
            symbol_ids = class_and_function_ids(nodes)

        recall: Recall = "broad" if cfg.patterns_recall == "broad" else "conservative"
        enricher = PatternTagEnricher(
            repo,
            the_judge,
            heuristics=PatternHeuristics(recall=recall),
            confidence_floor=cfg.confidence_floor,
            budget_usd=budget_usd if budget_usd is not None else cfg.budget_usd,
            concurrency=cfg.concurrency,
            commit=_git_commit(self._repo_path),
        )
        report = await enricher.enrich(self._store.graph, symbol_ids)
        await dirty.mark_clean("patterns", enricher.last_judged_ids)
        return report

    async def infer_governs(
        self, matcher: object | None = None, budget_usd: float | None = None
    ) -> Any:
        """LLM ``infer_governs`` pass (feat-010): for ADRs whose prose names no
        code, match the decision text against repo symbols and write ``GOVERNS``
        edges with ``llm`` provenance. Only decisions with zero *parsed* GOVERNS
        are touched. Builds the matcher from ``EnrichConfig`` (provider) unless one
        is supplied; budget from ``knowledge.infer_budget_usd``. Explicit call only
        (``ckg enrich --decisions``); returns a ``GovernsReport``."""
        from agentforge_graph.config import EnrichConfig, KnowledgeConfig
        from agentforge_graph.enrich import DecisionGovernsInferencer, GovernsMatcher

        ecfg = EnrichConfig.load(self._config)
        kcfg = KnowledgeConfig.load(self._config)
        repo = Path(self._repo_path).resolve().name
        if isinstance(matcher, GovernsMatcher):
            the_matcher: GovernsMatcher = matcher
        else:
            from agentforge_graph.enrich.registry import governs_matcher_from_config

            the_matcher = governs_matcher_from_config(ecfg)

        inferencer = DecisionGovernsInferencer(
            repo,
            the_matcher,
            confidence_floor=ecfg.confidence_floor,
            budget_usd=budget_usd if budget_usd is not None else kcfg.infer_budget_usd,
            commit=_git_commit(self._repo_path),
        )
        return await inferencer.enrich(self._store.graph)

    async def tagged(self, pattern: str, min_confidence: float = 0.7) -> list[TaggedInfo]:
        """Symbols carrying ``pattern`` above ``min_confidence`` (feat-012)."""
        from agentforge_graph.core import EdgeKind, SymbolID
        from agentforge_graph.enrich import TaggedInfo, pattern_tag_id

        repo = Path(self._repo_path).resolve().name
        tag_id = pattern_tag_id(repo, pattern)
        if await self._store.graph.get(tag_id) is None:
            return []
        out: list[TaggedInfo] = []
        for e in await self._store.graph.adjacent(tag_id, [EdgeKind.TAGGED], "in"):
            conf = float(e.attrs.get("confidence", 0.0))
            if conf >= min_confidence and SymbolID.parse(e.src).descriptor:
                out.append(
                    TaggedInfo(
                        symbol_id=e.src,
                        pattern=pattern,
                        confidence=conf,
                        rationale=str(e.attrs.get("rationale", "")),
                    )
                )
        out.sort(key=lambda t: t.confidence, reverse=True)
        return out

    async def summarize(
        self, summarizer: object | None = None, budget_usd: float | None = None
    ) -> Any:
        """Bottom-up module summaries (feat-012): file summaries + one repo
        summary, embedded for concept search. Drains DirtySet("summaries") if
        non-empty, else summarizes all files. Builds the Bedrock summarizer +
        embedder from config unless supplied. Explicit call only."""
        from agentforge_graph.config import EmbedConfig, EnrichConfig, StoreConfig
        from agentforge_graph.core import GraphQuery, NodeKind, SymbolID
        from agentforge_graph.embed import embedder_from_config
        from agentforge_graph.enrich import Summarizer, SummaryEnricher

        from .incremental import DirtySet

        cfg = EnrichConfig.load(self._config)
        repo = Path(self._repo_path).resolve().name
        root = resolve_root(self._repo_path, StoreConfig.load(self._config))
        if isinstance(summarizer, Summarizer):
            the_summarizer: Summarizer = summarizer
        else:
            from agentforge_graph.enrich.registry import summarizer_from_config

            the_summarizer = summarizer_from_config(cfg)  # ENH-003: provider-selected

        files = (
            await self._store.graph.query(GraphQuery(kinds=[NodeKind.FILE], limit=10**9))
        ).nodes
        dirty = DirtySet(root)
        dirty_ids = await dirty.dirty_for("summaries")
        if dirty_ids:  # dirty entries are symbol ids → the files that contain them
            paths = {SymbolID.parse(i).path for i in dirty_ids}
            file_ids = [n.id for n in files if SymbolID.parse(n.id).path in paths]
        else:
            file_ids = [n.id for n in files]

        enricher = SummaryEnricher(
            repo,
            the_summarizer,
            embedder=embedder_from_config(EmbedConfig.load(self._config)),
            max_words=cfg.summary_max_words,
            levels=cfg.summary_levels,
            budget_usd=budget_usd if budget_usd is not None else cfg.budget_usd,
            concurrency=cfg.concurrency,
            commit=_git_commit(self._repo_path),
        )
        report = await enricher.enrich(self._store, file_ids)
        done_paths = {SymbolID.parse(f).path for f in enricher.last_done_ids}
        await dirty.mark_clean(
            "summaries", [i for i in dirty_ids if SymbolID.parse(i).path in done_paths]
        )
        return report

    async def summaries(self, level: str | None = None) -> list[SummaryInfo]:
        """Stored module summaries (feat-012), optionally filtered by level."""
        from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind
        from agentforge_graph.enrich import SummaryInfo

        nodes = (
            await self._store.graph.query(GraphQuery(kinds=[NodeKind.SUMMARY], limit=10**9))
        ).nodes
        out: list[SummaryInfo] = []
        for n in nodes:
            lvl = str(n.attrs.get("level", ""))
            if level is not None and lvl != level:
                continue
            targets = await self._store.graph.adjacent(n.id, [EdgeKind.SUMMARIZES], "out")
            out.append(
                SummaryInfo(
                    target=targets[0].dst if targets else "",
                    level=lvl,
                    text=str(n.attrs.get("text", "")),
                    path=str(n.attrs.get("path", "")),
                )
            )
        out.sort(key=lambda s: (s.level, s.path))
        return out

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
