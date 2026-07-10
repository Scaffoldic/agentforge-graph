"""Process-lifetime engine holder behind the MCP tools.

Opened lazily on first tool call so ``code_graph_tools(".")`` can be built
synchronously and passed straight to ``Agent(tools=…)`` / the MCP server.
This module (and the whole ``serve`` package) is the framework-facing layer —
it may import ``agentforge`` (ADR-0001 exception); the engine packages do not.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Protocol

from agentforge_graph.config import (
    ConfigSource,
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


class EngineProvider(Protocol):
    """What the tools need from their engine — a single ``_Engine`` or a
    ``FederatedEngine`` over many members (ENH-020). ``targets`` returns the
    engines a survey tool fans across (tagged by service); ``one`` returns the
    single engine a pinpoint tool operates on."""

    def targets(self, service: str = "") -> list[tuple[str, _Engine]]: ...

    def one(self, service: str = "") -> _Engine: ...


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
    def __init__(self, repo_path: str | Path = ".", config: ConfigSource = None) -> None:
        from agentforge_graph.config import resolve_config

        self.repo_path = repo_path
        # discover agentforge.yaml app: / ckg.yaml when no explicit path is given
        self.config = resolve_config(config, repo_path)
        self.serve = ServeConfig.load(self.config)
        self._cg: CodeGraph | None = None
        self._retriever: Retriever | None = None
        self._repomap: RepoMap | None = None

    def targets(self, service: str = "") -> list[tuple[str, _Engine]]:
        """The engine(s) a federation-aware tool should fan across (ENH-020).
        A single engine is its own sole target, tagged with the empty service so
        callers preserve the non-federated output shape; ``service`` is ignored."""
        return [("", self)]

    def one(self, service: str = "") -> _Engine:
        """The single engine a pinpoint tool operates on; ``service`` is ignored
        for a non-federated engine (ENH-020)."""
        return self

    async def code_graph(self) -> CodeGraph:
        if self._cg is None:
            self._cg = await CodeGraph.open(self.repo_path, self.config)
        return self._cg

    async def retriever(self) -> Retriever:
        if self._retriever is None:
            from agentforge_graph.retrieve.rerank import reranker_from_config

            cg = await self.code_graph()
            embedder = embedder_from_config(EmbedConfig.load(self.config))
            rcfg = RetrieveConfig.load(self.config)
            # ENH-009: honor retrieve.rerank over MCP too (previously ignored here).
            self._retriever = Retriever(
                cg.store,
                embedder,
                rcfg,
                reranker=reranker_from_config(
                    rcfg.rerank, rcfg.rerank_weight, rcfg.rerank_model, rcfg.rerank_region
                ),
            )
        return self._retriever

    async def repomap(self) -> RepoMap:
        if self._repomap is None:
            cg = await self.code_graph()
            self._repomap = RepoMap(cg.store, RepoMapConfig.load(self.config))
        return self._repomap

    def _store_root(self) -> Path:
        from agentforge_graph.store import resolve_root

        return resolve_root(self.repo_path, StoreConfig.load(self.config))

    def _meta(self) -> Any:
        from agentforge_graph.ingest.incremental import IndexMeta

        return IndexMeta.load(self._store_root())

    async def staleness(self) -> dict[str, Any]:
        """Cheap envelope: the indexed commit + dirty flag, read from the
        persisted manifest (feat-004) rather than probed from a node."""
        meta = self._meta()
        head = _git_head(self.repo_path)
        return {
            "indexed_commit": meta.indexed_commit,
            "dirty": bool(head) and bool(meta.indexed_commit) and head != meta.indexed_commit,
        }

    async def routes(self, method: str = "", path: str = "") -> dict[str, Any]:
        """Extracted endpoints (feat-011), optionally filtered by HTTP method
        and/or path prefix, wrapped in the staleness envelope."""
        cg = await self.code_graph()
        items = [r.to_dict() for r in await cg.routes()]
        if method:
            items = [r for r in items if str(r["method"]).upper() == method.upper()]
        if path:
            # ENH-011: match the cross-file composed path or the base path, so a
            # query by the real URL ("/api/users") finds a prefixed route.
            items = [
                r
                for r in items
                if str(r.get("path_pattern") or r["path"]).startswith(path)
                or str(r["path"]).startswith(path)
            ]
        return {
            "routes": items,
            "count": len(items),
            **(await self.staleness()),
            "tool_api_version": TOOL_API_VERSION,
        }

    async def decisions(self, scope: str = "", status: str = "") -> dict[str, Any]:
        """Architecture decisions (feat-010), optionally filtered by governed
        path ``scope`` and ``status``, wrapped in the staleness envelope."""
        cg = await self.code_graph()
        items = [
            d.to_dict() for d in await cg.decisions(scope=scope or None, status=status or None)
        ]
        return {
            "decisions": items,
            "count": len(items),
            **(await self.staleness()),
            "tool_api_version": TOOL_API_VERSION,
        }

    async def explain(self, symbol_id: str) -> dict[str, Any]:
        """A symbol's LLM summary + design-pattern tags (feat-012) + its 1-hop
        typed facts — the reserved ckg_explain."""
        from agentforge_graph.core import EdgeKind, NodeKind, SymbolID

        cg = await self.code_graph()
        node = await cg.store.graph.get(symbol_id)
        tags: list[dict[str, Any]] = []
        facts: list[dict[str, str]] = []
        if node is not None:
            for e in await cg.store.graph.adjacent(symbol_id, [EdgeKind.TAGGED], "out"):
                target = await cg.store.graph.get(e.dst)
                tags.append(
                    {
                        "pattern": target.name if target else "",
                        "confidence": e.attrs.get("confidence", 0.0),
                        "rationale": e.attrs.get("rationale", ""),
                    }
                )
            for e in await cg.store.graph.adjacent(symbol_id, None, "both"):
                if e.kind is not EdgeKind.TAGGED:
                    facts.append({"src": e.src, "dst": e.dst, "kind": e.kind.value})
        # the owning file's summary, if one exists (feat-012)
        summary = ""
        if node is not None:
            path = SymbolID.parse(symbol_id).path
            for n in (
                await cg.store.graph.query(GraphQuery(kinds=[NodeKind.SUMMARY], limit=10**9))
            ).nodes:
                if str(n.attrs.get("level")) == "file" and str(n.attrs.get("path")) == path:
                    summary = str(n.attrs.get("text", ""))
                    break
        return {
            "symbol_id": symbol_id,
            "name": node.name if node else "",
            "kind": node.kind.value if node else "",
            "summary": summary,
            "tags": tags,
            "facts": facts,
            **(await self.staleness()),
            "tool_api_version": TOOL_API_VERSION,
        }

    async def history(self, symbol_id: str) -> dict[str, Any]:
        """A symbol's git evolution (feat-009): introduced / last-changed /
        churn / authors / lifecycle events, wrapped in the staleness envelope."""
        cg = await self.code_graph()
        hist = await cg.history(symbol_id)
        body: dict[str, Any] = (
            hist.model_dump() if hist is not None else {"symbol_id": symbol_id, "available": False}
        )
        return {**body, **(await self.staleness()), "tool_api_version": TOOL_API_VERSION}

    async def query_graph(self, query: str, limit: int | None = None) -> dict[str, Any]:
        """feat-015: run a read-only structural query, wrapped in the staleness
        envelope. A ``QueryError`` (bad syntax / vocabulary / capability / a
        non-query backend) is returned as a structured ``error`` — never raised
        into the tool layer."""
        from agentforge_graph.config import QueryConfig
        from agentforge_graph.store.query import QUERY_LANG_VERSION, QueryError

        qcfg = QueryConfig.load(self.config)
        cg = await self.code_graph()
        envelope = {
            **(await self.staleness()),
            "tool_api_version": TOOL_API_VERSION,
            "query_lang_version": QUERY_LANG_VERSION,
        }
        if not qcfg.enabled:
            return {"error": "the query surface is disabled (query.enabled=false)", **envelope}
        try:
            rt = await cg.query_graph(query, qcfg.to_settings(limit))
        except QueryError as exc:
            return {"error": str(exc), **envelope}
        return {
            "columns": list(rt.columns),
            "rows": [list(r) for r in rt.rows],
            "truncated": rt.truncated,
            "stopped_reason": rt.stopped_reason,
            **envelope,
        }

    async def status(self) -> dict[str, Any]:
        from agentforge_graph.config import DocGenConfig
        from agentforge_graph.docgen import DOC_LANG_VERSION
        from agentforge_graph.store.query import QUERY_LANG_VERSION

        dcfg = DocGenConfig.load(self.config)

        meta = self._meta()
        cg = await self.code_graph()
        nodes = (await cg.store.graph.query(GraphQuery(limit=_ALL))).nodes
        head = _git_head(self.repo_path)
        dirty = bool(head) and bool(meta.indexed_commit) and head != meta.indexed_commit
        by_kind: dict[str, int] = {}
        for n in nodes:
            by_kind[n.kind.value] = by_kind.get(n.kind.value, 0) + 1
        store_root = self._store_root()
        return {
            "indexed_commit": meta.indexed_commit,
            "head_commit": head,
            "dirty": dirty,
            "files_indexed": len(meta.files),
            "nodes": len(nodes),
            "by_kind": by_kind,
            "temporal": await cg.temporal_status(),
            "store_path": str(store_root),
            "query": {
                "enabled": cg.query_enabled,
                "lang_version": QUERY_LANG_VERSION,
                "capabilities": sorted(cg.query_capabilities),
            },
            "docgen": {
                "enabled": dcfg.enabled,
                "types": list(dcfg.types),
                "doc_lang_version": DOC_LANG_VERSION,
            },
            "tool_api_version": TOOL_API_VERSION,
        }

    async def close(self) -> None:
        if self._cg is not None:
            await self._cg.close()
