"""``CodeGraph`` — the top-level user facade (spec §4.1).

``index`` builds the embedded store (feat-003), runs the pipeline, and
returns a handle exposing the ``Store`` and the ``IndexReport``. ``open``
re-opens an existing index without re-indexing. This is the
``CodeGraph.open`` feat-003 deferred here (where ``index`` lives).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from agentforge_graph.store import Store

from .pack import PackRegistry
from .packs import BUILTIN_PACKS, builtin_registry
from .pipeline import IngestPipeline
from .report import IndexReport
from .source import RepoSource

# IngestConfig is read for excludes/limits; keep the import local-ish to the call.


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


class CodeGraph:
    def __init__(self, store: Store, report: IndexReport | None = None) -> None:
        self._store = store
        self._report = report

    @classmethod
    async def index(
        cls,
        repo_path: str | Path = ".",
        languages: str | list[str] | None = None,
        config: str | Path | None = None,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> CodeGraph:
        from agentforge_graph.config import IngestConfig

        store = await Store.open(repo_path, config)
        ingest = IngestConfig.load(config)
        registry = _registry_for(languages if languages is not None else ingest.languages)
        source = RepoSource(
            repo_path,
            include=include,
            exclude=ingest.exclude + (exclude or []),
            max_file_kb=ingest.max_file_kb,
        )
        repo = Path(repo_path).resolve().name
        pipeline = IngestPipeline(repo=repo, commit=_git_commit(repo_path))
        report = await pipeline.run(source, store.graph, registry)
        return cls(store, report)

    @classmethod
    async def open(cls, repo_path: str | Path = ".", config: str | Path | None = None) -> CodeGraph:
        return cls(await Store.open(repo_path, config))

    @property
    def store(self) -> Store:
        return self._store

    def stats(self) -> IndexReport:
        if self._report is None:
            raise RuntimeError("no index report: open() does not index — use index()")
        return self._report

    async def close(self) -> None:
        await self._store.close()
