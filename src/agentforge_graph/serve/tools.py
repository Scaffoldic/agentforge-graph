"""The six read-only CKG tools (feat-008), thin over feat-006/007.

Each is an AgentForge ``Tool`` holding the shared ``_Engine``; ``run`` clamps
params to ``ServeConfig`` and returns a JSON string (structured) or text (the
map) — MCP coerces results via ``str()``, so JSON keeps structure intact.
Every structured envelope carries ``indexed_commit`` + ``dirty`` (staleness)
and a ``truncated`` flag. Names & schemas are locked at v1.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from agentforge_core.contracts.tool import Tool
from pydantic import BaseModel, Field

from agentforge_graph.chunking import estimate_tokens
from agentforge_graph.core import EdgeKind, GraphQuery

from .engine import TOOL_API_VERSION, _Engine


class RepoMapInput(BaseModel):
    budget_tokens: int = Field(default=2000, description="token budget for the map")
    focus: list[str] = Field(
        default_factory=list, description="paths or symbol ids to rank the map around"
    )


class SearchInput(BaseModel):
    query: str = Field(description="natural-language question about the code")
    k: int = Field(default=8, description="number of vector hits (clamped to serve.max_k)")
    mode: str = Field(default="context", description="context | similar | definition | impact")


class SymbolInput(BaseModel):
    symbol_id: str = Field(default="", description="exact symbol id, if known")
    name: str = Field(default="", description="symbol name (use with path) when id is unknown")
    path: str = Field(default="", description="file path for a name lookup")


class ImpactInput(BaseModel):
    symbol_id: str = Field(description="symbol whose reverse dependencies to trace")
    depth: int = Field(default=1, description="hops (clamped to serve.max_depth)")


class NeighborsInput(BaseModel):
    symbol_id: str = Field(description="symbol id")
    edge_kinds: list[str] = Field(
        default_factory=list, description="edge kinds to follow (e.g. CALLS, CONTAINS); default all"
    )
    depth: int = Field(default=1, description="hops (clamped to serve.max_depth)")


class RoutesInput(BaseModel):
    method: str = Field(default="", description="filter by HTTP method, e.g. GET (optional)")
    path: str = Field(default="", description="filter by path prefix, e.g. /users (optional)")


class DecisionsInput(BaseModel):
    scope: str = Field(default="", description="restrict to decisions governing a path prefix")
    status: str = Field(default="", description="filter by status, e.g. accepted (optional)")


class ExplainInput(BaseModel):
    symbol_id: str = Field(description="exact symbol id to explain")


class EmptyInput(BaseModel):
    pass


class _CkgTool(Tool):
    capabilities: ClassVar[frozenset[str]] = frozenset()

    def __init__(self, engine: _Engine) -> None:
        self._engine = engine

    async def _pack_json(self, pack: Any) -> str:
        data = pack.to_dict()
        data.update(await self._engine.staleness())
        data["tool_api_version"] = TOOL_API_VERSION
        cap = self._engine.serve.response_token_cap
        truncated = False
        while len(data.get("items", [])) > 1 and estimate_tokens(json.dumps(data)) > cap:
            data["items"].pop()
            truncated = True
        if truncated:
            data.setdefault("notes", []).append("response truncated to fit response_token_cap")
        data["truncated"] = truncated
        return json.dumps(data, indent=2)


class CkgRepoMap(_CkgTool):
    name: ClassVar[str] = "ckg_repo_map"
    description: ClassVar[str] = (
        "Orient in a codebase: a budget-aware, centrality-ranked map of the most "
        "structurally important symbols (signatures), grouped by file. Call this FIRST "
        "to understand an unfamiliar repo. Pass `focus` (paths/symbol ids) to rank the "
        "map around a working set."
    )
    input_schema: ClassVar[type[BaseModel]] = RepoMapInput

    async def run(self, **kwargs: Any) -> str:
        repomap = await self._engine.repomap()
        budget = min(int(kwargs.get("budget_tokens", 2000)), self._engine.serve.response_token_cap)
        text = await repomap.render(budget_tokens=budget, focus=kwargs.get("focus") or None)
        return text or "(empty repo map)"


class CkgSearch(_CkgTool):
    name: ClassVar[str] = "ckg_search"
    description: ClassVar[str] = (
        "Search the codebase for code relevant to a natural-language question. Returns "
        "ranked, CONNECTED context: matching chunks plus their symbols and neighbors. "
        "`mode`: 'context' (default), 'similar' (just similar code), 'definition' (a "
        "symbol's chunks), 'impact' (reverse deps — prefer ckg_impact). Take a result's "
        "`id` to chain into ckg_impact / ckg_neighbors / ckg_symbol."
    )
    input_schema: ClassVar[type[BaseModel]] = SearchInput

    async def run(self, **kwargs: Any) -> str:
        retriever = await self._engine.retriever()
        k = min(int(kwargs.get("k", 8)), self._engine.serve.max_k)
        pack = await retriever.retrieve(
            query=kwargs["query"], k=k, mode=kwargs.get("mode", "context")
        )
        return await self._pack_json(pack)


class CkgSymbol(_CkgTool):
    name: ClassVar[str] = "ckg_symbol"
    description: ClassVar[str] = (
        "Look up a specific symbol's definition: the symbol, its chunks and members. "
        "Provide `symbol_id` (exact) or `name` + `path`. When the temporal layer is "
        "enabled, items carry `temporal` (churn_90d, top_authors, introduced, "
        "last_changed) — recency/ownership signals for triage."
    )
    input_schema: ClassVar[type[BaseModel]] = SymbolInput

    async def run(self, **kwargs: Any) -> str:
        symbol_id = kwargs.get("symbol_id", "")
        if not symbol_id:
            cg = await self._engine.code_graph()
            res = await cg.store.graph.query(
                GraphQuery(name=kwargs.get("name") or None, path_prefix=kwargs.get("path") or None)
            )
            symbol_id = res.nodes[0].id if res.nodes else ""
        if not symbol_id:
            return json.dumps({"error": "symbol not found", "tool_api_version": TOOL_API_VERSION})
        retriever = await self._engine.retriever()
        depth = min(1, self._engine.serve.max_depth)
        pack = await retriever.retrieve(symbol=symbol_id, mode="definition", depth=depth)
        return await self._pack_json(pack)


class CkgImpact(_CkgTool):
    name: ClassVar[str] = "ckg_impact"
    description: ClassVar[str] = (
        "Find what DEPENDS ON a symbol (reverse CALLS/IMPORTS/IMPLEMENTS): 'who calls "
        "this', 'what breaks if I change this'. The impact question grep cannot answer."
    )
    input_schema: ClassVar[type[BaseModel]] = ImpactInput

    async def run(self, **kwargs: Any) -> str:
        retriever = await self._engine.retriever()
        depth = min(int(kwargs.get("depth", 1)), self._engine.serve.max_depth)
        pack = await retriever.retrieve(symbol=kwargs["symbol_id"], mode="impact", depth=depth)
        return await self._pack_json(pack)


class CkgNeighbors(_CkgTool):
    name: ClassVar[str] = "ckg_neighbors"
    description: ClassVar[str] = (
        "List a symbol's typed graph neighbors (edges in both directions), optionally "
        "filtered by edge kind (CALLS, CONTAINS, IMPORTS, INHERITS, REFERENCES, CHUNK_OF)."
    )
    input_schema: ClassVar[type[BaseModel]] = NeighborsInput

    async def run(self, **kwargs: Any) -> str:
        cg = await self._engine.code_graph()
        kinds = [EdgeKind(k) for k in kwargs.get("edge_kinds", [])] or None
        depth = min(int(kwargs.get("depth", 1)), self._engine.serve.max_depth)
        start = kwargs["symbol_id"]
        seen: set[tuple[str, str, str]] = set()
        edges: list[dict[str, str]] = []
        frontier = {start}
        visited = {start}
        for _ in range(depth):
            nxt: set[str] = set()
            for nid in frontier:
                for e in await cg.store.graph.adjacent(nid, kinds, "both"):
                    key = (e.src, e.dst, e.kind.value)
                    if key not in seen:
                        seen.add(key)
                        edges.append(
                            {
                                "src": e.src,
                                "dst": e.dst,
                                "kind": e.kind.value,
                                "provenance": e.provenance.source.value,
                            }
                        )
                    other = e.dst if e.src == nid else e.src
                    if other not in visited:
                        visited.add(other)
                        nxt.add(other)
            frontier = nxt
        envelope = await self._engine.staleness()
        return json.dumps(
            {"symbol_id": start, "edges": edges, **envelope, "tool_api_version": TOOL_API_VERSION},
            indent=2,
        )


class CkgStatus(_CkgTool):
    name: ClassVar[str] = "ckg_status"
    description: ClassVar[str] = (
        "Report index status: the indexed git commit, whether it is stale vs the working "
        "tree (`dirty`), node counts by kind, and the tool-API version. If results seem "
        "out of date and `dirty` is true, tell the user to re-run `ckg index`."
    )
    input_schema: ClassVar[type[BaseModel]] = EmptyInput

    async def run(self, **kwargs: Any) -> str:
        return json.dumps(await self._engine.status(), indent=2)


class CkgRoutes(_CkgTool):
    name: ClassVar[str] = "ckg_routes"
    description: ClassVar[str] = (
        "List the app's HTTP API surface: every framework route (e.g. FastAPI) with its "
        "method, path pattern and handler symbol id. Filter by `method` and/or `path` prefix. "
        "Take a route's `handler` into ckg_symbol / ckg_impact to see the handler and what it "
        "touches. Returns empty if no web framework is detected."
    )
    input_schema: ClassVar[type[BaseModel]] = RoutesInput

    async def run(self, **kwargs: Any) -> str:
        data = await self._engine.routes(
            method=kwargs.get("method", ""), path=kwargs.get("path", "")
        )
        return json.dumps(data, indent=2)


class CkgDecisions(_CkgTool):
    name: ClassVar[str] = "ckg_decisions"
    description: ClassVar[str] = (
        "List the architecture decisions (ADRs) governing the codebase: each decision's "
        "status, date, title and the symbols/files it governs. Filter by `scope` (a path "
        "prefix the decision governs) and/or `status` (e.g. accepted). Call this before a "
        "refactor to check no documented decision forbids the change. Empty if no ADRs."
    )
    input_schema: ClassVar[type[BaseModel]] = DecisionsInput

    async def run(self, **kwargs: Any) -> str:
        data = await self._engine.decisions(
            scope=kwargs.get("scope", ""), status=kwargs.get("status", "")
        )
        return json.dumps(data, indent=2)


class CkgExplain(_CkgTool):
    name: ClassVar[str] = "ckg_explain"
    description: ClassVar[str] = (
        "Explain a symbol: its LLM-derived design-pattern tags (e.g. 'Repository', with "
        "confidence + rationale) and its 1-hop typed graph facts. Use to learn what role a "
        "class/function plays before changing it. Tags are [llm]-provenance; empty until "
        "`ckg enrich` has run."
    )
    input_schema: ClassVar[type[BaseModel]] = ExplainInput

    async def run(self, **kwargs: Any) -> str:
        return json.dumps(await self._engine.explain(kwargs["symbol_id"]), indent=2)


ALL_TOOLS = [
    CkgRepoMap,
    CkgSearch,
    CkgSymbol,
    CkgImpact,
    CkgNeighbors,
    CkgStatus,
    CkgRoutes,
    CkgDecisions,
    CkgExplain,
]
