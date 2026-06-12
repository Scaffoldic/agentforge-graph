"""``CodeGraph`` — the top-level user facade (spec §4.1).

``index`` builds the embedded store (feat-003), runs the pipeline, and
returns a handle exposing the ``Store`` and the ``IndexReport``. ``open``
re-opens an existing index without re-indexing. This is the
``CodeGraph.open`` feat-003 deferred here (where ``index`` lives).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from agentforge_graph.store import Store

from .pack import PackRegistry
from .packs import BUILTIN_PACKS, builtin_registry
from .pipeline import IngestPipeline
from .report import IndexReport
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
    ) -> CodeGraph:
        store = await Store.open(repo_path, config)
        source, registry = _source_registry(repo_path, config, languages, include, exclude)
        repo = Path(repo_path).resolve().name
        pipeline = IngestPipeline(repo=repo, commit=_git_commit(repo_path))
        report = await pipeline.run(source, store.graph, registry)
        cg = cls(store, repo_path, config, languages, report)
        if embed:
            await cg.embed()
        return cg

    @classmethod
    async def open(
        cls,
        repo_path: str | Path = ".",
        config: str | Path | None = None,
        languages: str | list[str] | None = None,
    ) -> CodeGraph:
        return cls(await Store.open(repo_path, config), repo_path, config, languages)

    async def embed(self, embedder: object | None = None) -> EmbedReport:
        """Chunk and embed everything indexed. Builds the embedder from
        ``EmbedConfig`` if not supplied."""
        from agentforge_graph.chunking import CASTChunker
        from agentforge_graph.config import ChunkingConfig, EmbedConfig
        from agentforge_graph.embed import Embedder, EmbedPipeline, embedder_from_config

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
        self._embed_report = await pipeline.run(self._store, source, registry)
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
