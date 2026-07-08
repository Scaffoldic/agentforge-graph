"""The read-only CKG tools (feat-008), thin over feat-006/007/009.

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

from .engine import TOOL_API_VERSION, EngineProvider, _Engine
from .federation import AmbiguousMember, MemberNotFound


class _Fed(BaseModel):
    """Shared input field for federated serving (ENH-020). Inert for a single
    repo; over a workspace it targets one member by name (survey tools fan over
    all members when omitted; pinpoint tools require it when several exist)."""

    service: str = Field(
        default="",
        description="federated: target one workspace member by name (omit to fan / auto-select)",
    )


class RepoMapInput(_Fed):
    budget_tokens: int = Field(default=2000, description="token budget for the map")
    focus: list[str] = Field(
        default_factory=list, description="paths or symbol ids to rank the map around"
    )


class SearchInput(_Fed):
    query: str = Field(description="natural-language question about the code")
    k: int = Field(default=8, description="number of vector hits (clamped to serve.max_k)")
    mode: str = Field(default="context", description="context | similar | definition | impact")


class SymbolInput(_Fed):
    symbol_id: str = Field(default="", description="exact symbol id, if known")
    name: str = Field(default="", description="symbol name (use with path) when id is unknown")
    path: str = Field(default="", description="file path for a name lookup")


class ImpactInput(_Fed):
    symbol_id: str = Field(description="symbol whose reverse dependencies to trace")
    depth: int = Field(default=1, description="hops (clamped to serve.max_depth)")


class NeighborsInput(_Fed):
    symbol_id: str = Field(description="symbol id")
    edge_kinds: list[str] = Field(
        default_factory=list, description="edge kinds to follow (e.g. CALLS, CONTAINS); default all"
    )
    depth: int = Field(default=1, description="hops (clamped to serve.max_depth)")


class RoutesInput(_Fed):
    method: str = Field(default="", description="filter by HTTP method, e.g. GET (optional)")
    path: str = Field(default="", description="filter by path prefix, e.g. /users (optional)")


class DecisionsInput(_Fed):
    scope: str = Field(default="", description="restrict to decisions governing a path prefix")
    status: str = Field(default="", description="filter by status, e.g. accepted (optional)")


class ExplainInput(_Fed):
    symbol_id: str = Field(description="exact symbol id to explain")


class HistoryInput(_Fed):
    symbol_id: str = Field(description="exact symbol id whose git history to report")


class QueryInput(_Fed):
    query: str = Field(
        description="a read-only structural query in the Cypher subset "
        "(MATCH … WHERE … RETURN …); see ckg_status for the language version"
    )
    limit: int | None = Field(default=None, description="cap rows (clamped to the server max)")


class EmptyInput(_Fed):
    pass


class _CkgTool(Tool):
    capabilities: ClassVar[frozenset[str]] = frozenset()
    # Serve-level capability gates: this tool is registered only when the backend
    # provides every marker here (feat-015 capability-driven registration).
    requires: ClassVar[frozenset[str]] = frozenset()

    def __init__(self, engine: EngineProvider) -> None:
        self._engine = engine

    async def _pack_json(self, engine: _Engine, pack: Any) -> str:
        data = pack.to_dict()
        data.update(await engine.staleness())
        data["tool_api_version"] = TOOL_API_VERSION
        cap = engine.serve.response_token_cap
        truncated = False
        while len(data.get("items", [])) > 1 and estimate_tokens(json.dumps(data)) > cap:
            data["items"].pop()
            truncated = True
        if truncated:
            data.setdefault("notes", []).append("response truncated to fit response_token_cap")
        data["truncated"] = truncated
        return json.dumps(data, indent=2)

    # --- ENH-020 federation helpers ---------------------------------------

    def _is_single(self, targets: list[tuple[str, _Engine]]) -> bool:
        """True for a non-federated engine — preserve the legacy output shape."""
        return len(targets) == 1 and targets[0][0] == ""

    def _resolve_one(self, kwargs: dict[str, Any]) -> tuple[_Engine | None, str | None]:
        """Pick the single member a pinpoint tool targets, or a JSON error string
        when the ``service`` is unknown / ambiguous (ENH-020)."""
        try:
            return self._engine.one(kwargs.get("service", "")), None
        except (MemberNotFound, AmbiguousMember) as e:
            return None, json.dumps({"error": str(e), "tool_api_version": TOOL_API_VERSION})

    def _resolve_targets(
        self, kwargs: dict[str, Any]
    ) -> tuple[list[tuple[str, _Engine]] | None, str | None]:
        """The members a survey tool fans across, or a JSON error string when the
        named ``service`` is unknown (ENH-020)."""
        try:
            return self._engine.targets(kwargs.get("service", "")), None
        except MemberNotFound as e:
            return None, json.dumps({"error": str(e), "tool_api_version": TOOL_API_VERSION})

    def _merge(self, key: str, parts: list[tuple[str, dict[str, Any]]], cap: int) -> str:
        """Fan-merge per-member result dicts: concatenate their ``key`` list with
        each item tagged by ``service``, fold staleness into a per-service map,
        and re-truncate to ``cap`` (ENH-020)."""
        items: list[dict[str, Any]] = []
        services: dict[str, Any] = {}
        for name, d in parts:
            for it in d.get(key, []):
                items.append({**it, "service": name})
            services[name] = {
                "indexed_commit": d.get("indexed_commit", ""),
                "dirty": d.get("dirty", False),
            }
        data: dict[str, Any] = {
            key: items,
            "count": len(items),
            "services": services,
            "tool_api_version": TOOL_API_VERSION,
        }
        truncated = False
        while len(data[key]) > 1 and estimate_tokens(json.dumps(data)) > cap:
            data[key].pop()
            truncated = True
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
        eng, err = self._resolve_one(kwargs)
        if eng is None:
            return err or ""
        repomap = await eng.repomap()
        budget = min(int(kwargs.get("budget_tokens", 2000)), eng.serve.response_token_cap)
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
        targets, err = self._resolve_targets(kwargs)
        if targets is None:
            return err or ""

        async def one(eng: _Engine) -> str:
            retriever = await eng.retriever()
            k = min(int(kwargs.get("k", 8)), eng.serve.max_k)
            pack = await retriever.retrieve(
                query=kwargs["query"], k=k, mode=kwargs.get("mode", "context")
            )
            return await self._pack_json(eng, pack)

        if self._is_single(targets):
            return await one(targets[0][1])
        parts = [(name, json.loads(await one(eng))) for name, eng in targets]
        return self._merge("items", parts, targets[0][1].serve.response_token_cap)


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
        eng, err = self._resolve_one(kwargs)
        if eng is None:
            return err or ""
        symbol_id = kwargs.get("symbol_id", "")
        if not symbol_id:
            cg = await eng.code_graph()
            res = await cg.store.graph.query(
                GraphQuery(name=kwargs.get("name") or None, path_prefix=kwargs.get("path") or None)
            )
            symbol_id = res.nodes[0].id if res.nodes else ""
        if not symbol_id:
            return json.dumps({"error": "symbol not found", "tool_api_version": TOOL_API_VERSION})
        retriever = await eng.retriever()
        depth = min(1, eng.serve.max_depth)
        pack = await retriever.retrieve(symbol=symbol_id, mode="definition", depth=depth)
        return await self._pack_json(eng, pack)


class CkgImpact(_CkgTool):
    name: ClassVar[str] = "ckg_impact"
    description: ClassVar[str] = (
        "Find what DEPENDS ON a symbol (reverse CALLS/IMPORTS/IMPLEMENTS): 'who calls "
        "this', 'what breaks if I change this'. The impact question grep cannot answer."
    )
    input_schema: ClassVar[type[BaseModel]] = ImpactInput

    async def run(self, **kwargs: Any) -> str:
        eng, err = self._resolve_one(kwargs)
        if eng is None:
            return err or ""
        retriever = await eng.retriever()
        depth = min(int(kwargs.get("depth", 1)), eng.serve.max_depth)
        pack = await retriever.retrieve(symbol=kwargs["symbol_id"], mode="impact", depth=depth)
        return await self._pack_json(eng, pack)


class CkgNeighbors(_CkgTool):
    name: ClassVar[str] = "ckg_neighbors"
    description: ClassVar[str] = (
        "List a symbol's typed graph neighbors (edges in both directions), optionally "
        "filtered by edge kind (CALLS, CONTAINS, IMPORTS, INHERITS, REFERENCES, CHUNK_OF)."
    )
    input_schema: ClassVar[type[BaseModel]] = NeighborsInput

    async def run(self, **kwargs: Any) -> str:
        eng, err = self._resolve_one(kwargs)
        if eng is None:
            return err or ""
        cg = await eng.code_graph()
        kinds = [EdgeKind(k) for k in kwargs.get("edge_kinds", [])] or None
        depth = min(int(kwargs.get("depth", 1)), eng.serve.max_depth)
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
        envelope = await eng.staleness()
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
        targets, err = self._resolve_targets(kwargs)
        if targets is None:
            return err or ""
        if self._is_single(targets):
            return json.dumps(await targets[0][1].status(), indent=2)
        services = {name: await eng.status() for name, eng in targets}
        return json.dumps({"services": services, "tool_api_version": TOOL_API_VERSION}, indent=2)


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
        targets, err = self._resolve_targets(kwargs)
        if targets is None:
            return err or ""

        async def one(eng: _Engine) -> dict[str, Any]:
            return await eng.routes(method=kwargs.get("method", ""), path=kwargs.get("path", ""))

        if self._is_single(targets):
            return json.dumps(await one(targets[0][1]), indent=2)
        parts = [(name, await one(eng)) for name, eng in targets]
        return self._merge("routes", parts, targets[0][1].serve.response_token_cap)


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
        targets, err = self._resolve_targets(kwargs)
        if targets is None:
            return err or ""

        async def one(eng: _Engine) -> dict[str, Any]:
            return await eng.decisions(
                scope=kwargs.get("scope", ""), status=kwargs.get("status", "")
            )

        if self._is_single(targets):
            return json.dumps(await one(targets[0][1]), indent=2)
        parts = [(name, await one(eng)) for name, eng in targets]
        return self._merge("decisions", parts, targets[0][1].serve.response_token_cap)


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
        eng, err = self._resolve_one(kwargs)
        if eng is None:
            return err or ""
        return json.dumps(await eng.explain(kwargs["symbol_id"]), indent=2)


class CkgHistory(_CkgTool):
    name: ClassVar[str] = "ckg_history"
    description: ClassVar[str] = (
        "Report a symbol's git evolution (feat-009 temporal): when it was introduced and "
        "last changed, churn over the last 30/90 days, its top authors, and its lifecycle "
        "events. Use to gauge recency/ownership before changing a symbol or to triage a "
        "regression. Returns `available: false` if the temporal layer is off or unindexed."
    )
    input_schema: ClassVar[type[BaseModel]] = HistoryInput

    async def run(self, **kwargs: Any) -> str:
        eng, err = self._resolve_one(kwargs)
        if eng is None:
            return err or ""
        return json.dumps(await eng.history(kwargs["symbol_id"]), indent=2)


class TraceInput(BaseModel):
    service: str = Field(description="the workspace member to trace from")
    direction: str = Field(
        default="downstream",
        description="downstream (services this one calls — data flow) | "
        "upstream (services that call this one — blast radius)",
    )
    depth: int = Field(default=10, description="max hops to follow (capped at 50)")


class CkgTrace(_CkgTool):
    name: ClassVar[str] = "ckg_trace"
    description: ClassVar[str] = (
        "Trace a request across services: from a starting service, walk the cross-service "
        "call graph `downstream` (what it calls — data flow) or `upstream` (who calls it — "
        "blast radius). Answers 'what does this service depend on' / 'which services break if "
        "I change this one'. Requires a federated workspace (serve-mcp --workspace)."
    )
    input_schema: ClassVar[type[BaseModel]] = TraceInput

    async def run(self, **kwargs: Any) -> str:
        fn = getattr(self._engine, "trace", None)
        if fn is None:
            return json.dumps(
                {
                    "error": "ckg_trace needs a federated workspace "
                    "(serve-mcp --workspace workspace.yaml)",
                    "tool_api_version": TOOL_API_VERSION,
                }
            )
        try:
            result = await fn(
                kwargs["service"],
                int(kwargs.get("depth", 10)),
                kwargs.get("direction", "downstream"),
            )
        except (MemberNotFound, ValueError) as e:
            return json.dumps({"error": str(e), "tool_api_version": TOOL_API_VERSION})
        return json.dumps(result, indent=2)


class CkgServicesMap(_CkgTool):
    name: ClassVar[str] = "ckg_services_map"
    description: ClassVar[str] = (
        "Show the org's CROSS-SERVICE call graph: which service calls which, matched "
        "by outbound HTTP client call (requests/httpx) to the route it hits in another "
        "service. Returns `edges` (from_service → to_service, method, path, handler) plus "
        "`unresolved` calls. Requires a federated workspace (serve-mcp --workspace)."
    )
    input_schema: ClassVar[type[BaseModel]] = EmptyInput

    async def run(self, **kwargs: Any) -> str:
        fn = getattr(self._engine, "service_map", None)
        if fn is None:
            return json.dumps(
                {
                    "error": "ckg_services_map needs a federated workspace "
                    "(serve-mcp --workspace workspace.yaml)",
                    "tool_api_version": TOOL_API_VERSION,
                }
            )
        return json.dumps(await fn(), indent=2)


class CkgQuery(_CkgTool):
    name: ClassVar[str] = "ckg_query"
    description: ClassVar[str] = (
        "Escape hatch for PRECISE STRUCTURAL questions no typed verb covers — e.g. "
        "'classes tagged Repository with no inbound CALLS', 'interfaces implemented by "
        ">5 classes'. Read-only Cypher subset: MATCH patterns over the graph's node/edge "
        "kinds, WHERE (comparisons, IN, STARTS/ENDS WITH, CONTAINS, pattern existence), "
        "RETURN with count/min/max/avg, ORDER BY, LIMIT. For semantic 'find code about X' "
        "use ckg_search instead; for 'who calls this' use ckg_impact."
    )
    input_schema: ClassVar[type[BaseModel]] = QueryInput
    requires: ClassVar[frozenset[str]] = frozenset({"query"})

    async def run(self, **kwargs: Any) -> str:
        eng, err = self._resolve_one(kwargs)
        if eng is None:
            return err or ""
        result = await eng.query_graph(kwargs["query"], kwargs.get("limit"))
        return json.dumps(result, indent=2)


# The locked v1 tool set (single-repo). ``ckg_query`` is capability-gated —
# registered only when the backend is query-capable (feat-015). ``ckg_services_map``
# is federation-only and appended by ``federated_tools`` (ENH-020).
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
    CkgHistory,
    CkgQuery,
]
