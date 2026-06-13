"""Process-lifetime engine holder behind the MCP tools.

Opened lazily on first tool call so ``code_graph_tools(".")`` can be built
synchronously and passed straight to ``Agent(tools=…)`` / the MCP server.
This module (and the whole ``serve`` package) is the framework-facing layer —
it may import ``agentforge`` (ADR-0001 exception); the engine packages do not.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from agentforge_graph.config import (
    EmbedConfig,
    RepoMapConfig,
    RetrieveConfig,
    ServeConfig,
    StoreConfig,
)
from agentforge_graph.core import GraphQuery
from agentforge_graph.embed import embedder_from_config
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.repomap import RepoMap
from agentforge_graph.retrieve import Retriever

TOOL_API_VERSION = "1.0"
_ALL = 10_000_000


def _git_head(repo_path: str | Path) -> str:
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


class _Engine:
    def __init__(self, repo_path: str | Path = ".", config: str | Path | None = None) -> None:
        self.repo_path = repo_path
        self.config = config
        self.serve = ServeConfig.load(config)
        self._cg: CodeGraph | None = None
        self._retriever: Retriever | None = None
        self._repomap: RepoMap | None = None

    async def code_graph(self) -> CodeGraph:
        if self._cg is None:
            self._cg = await CodeGraph.open(self.repo_path, self.config)
        return self._cg

    async def retriever(self) -> Retriever:
        if self._retriever is None:
            cg = await self.code_graph()
            embedder = embedder_from_config(EmbedConfig.load(self.config))
            self._retriever = Retriever(cg.store, embedder, RetrieveConfig.load(self.config))
        return self._retriever

    async def repomap(self) -> RepoMap:
        if self._repomap is None:
            cg = await self.code_graph()
            self._repomap = RepoMap(cg.store, RepoMapConfig.load(self.config))
        return self._repomap

    def _meta(self) -> Any:
        from agentforge_graph.ingest.incremental import IndexMeta

        root = Path(self.repo_path) / StoreConfig.load(self.config).path
        return IndexMeta.load(root)

    async def staleness(self) -> dict[str, Any]:
        """Cheap envelope: the indexed commit + dirty flag, read from the
        persisted manifest (feat-004) rather than probed from a node."""
        meta = self._meta()
        head = _git_head(self.repo_path)
        return {
            "indexed_commit": meta.indexed_commit,
            "dirty": bool(head) and bool(meta.indexed_commit) and head != meta.indexed_commit,
        }

    async def status(self) -> dict[str, Any]:
        meta = self._meta()
        cg = await self.code_graph()
        nodes = (await cg.store.graph.query(GraphQuery(limit=_ALL))).nodes
        head = _git_head(self.repo_path)
        dirty = bool(head) and bool(meta.indexed_commit) and head != meta.indexed_commit
        by_kind: dict[str, int] = {}
        for n in nodes:
            by_kind[n.kind.value] = by_kind.get(n.kind.value, 0) + 1
        store_root = Path(self.repo_path) / StoreConfig.load(self.config).path
        return {
            "indexed_commit": meta.indexed_commit,
            "head_commit": head,
            "dirty": dirty,
            "files_indexed": len(meta.files),
            "nodes": len(nodes),
            "by_kind": by_kind,
            "store_path": str(store_root),
            "tool_api_version": TOOL_API_VERSION,
        }

    async def close(self) -> None:
        if self._cg is not None:
            await self._cg.close()
