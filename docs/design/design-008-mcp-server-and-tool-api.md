# Design Doc: feat-008 MCP server & tool API

> Per-feature design doc (design stage). Mirrors
> `docs/features/feat-008-mcp-server-and-tool-api.md`. The MVP exit.

---

## Metadata

| Field | Value |
|---|---|
| **Title** | feat-008 MCP server & AgentForge tool API |
| **Status** | accepted |
| **Owner** | kjoshi |
| **Created** | 2026-06-12 |
| **Last updated** | 2026-06-12 |
| **Related features** | feat-008 (this) · consumes feat-006, feat-007 · **MVP exit** |
| **Related ADRs** | ADR-0001 (layering — serve is the *framework* layer, the deliberate exception) |

---

## 1. Context

The serving layer: expose the engine to any agent (Claude Code, AgentForge
agents) as tools, from **one tool definition** bound two ways — native
AgentForge `Tool` instances *and* an MCP stdio server. This is the one
package that **intentionally imports `agentforge`** (the project's "reuse
framework rails" note); the deterministic engine packages stay framework-free.

**Framework API (verified, agentforge-py / agentforge-mcp 0.2.4):**
- `Tool` ABC = `agentforge_core.contracts.tool.Tool`: ClassVars `name`,
  `description`, `input_schema: type[BaseModel]`, `capabilities`, and
  `async def run(self, **kwargs) -> Any`.
- `agentforge_mcp.MCPServer.from_stdio(tools=[Tool], allowed=(...))` →
  `await server.serve()`. Registers tools; **result is coerced via
  `str(result)`** → structured tools return **JSON strings**.
- `Agent(tools=list[Tool])`.

## 2. Goals

- `agentforge_graph.serve` — the six locked v1 tools, each thin over
  feat-006/007, returning JSON (structured) or text (map).
- **One definition, two bindings**: `code_graph_tools(repo_path) ->
  list[Tool]` (Agent) and `serve_mcp(repo_path)` (MCP stdio), both from the
  same `Tool` instances.
- Read-only; guardrails (clamp `depth ≤ max_depth`, `k ≤ max_k`, response
  token cap) with explicit notes — feat-006's no-silent-caps rule carried
  through.
- `ckg serve-mcp` console entry; `ckg_status` reports indexed commit +
  staleness + the tool-API version.
- ≥90% coverage (tools driven directly + JSON-schema snapshots; the live
  stdio/agent loop is env-gated); `mypy --strict`; ruff.

## 3. Non-goals

- Write/annotate tools (post-1.0 — needs authz). HTTP/SSE transport (stdio
  at 0.1). Auto-indexing daemon (feat-004). The reserved tools
  `ckg_decisions`/`ckg_routes`/`ckg_explain` (registered when feat-010/011/012
  ship). The other nine languages.

## 4. Proposal

### 4.1 Package layout

```
src/agentforge_graph/serve/
  __init__.py     # code_graph_tools, serve_mcp, TOOL_API_VERSION
  engine.py       # _Engine: lazy-opened store + retriever + repomap + status
  tools.py        # the six Tool subclasses + their pydantic input schemas
  server.py       # serve_mcp(repo_path, config, refresh_on_call) -> coroutine
src/agentforge_graph/
  config.py       # + ServeConfig
  cli.py          # + `ckg serve-mcp`
```

`serve` **imports `agentforge`** — it is the framework layer, the ADR-0001
exception; **no layering test** applies to it (the engine packages keep
theirs). `agentforge-py`/`agentforge-mcp` are already base deps (CI has them).

### 4.2 `_Engine` (`engine.py`)

A process-lifetime holder, opened lazily on first tool call (tools are
constructed synchronously so `code_graph_tools(".")` works inline in
`Agent(tools=…)`):

```python
class _Engine:
    def __init__(self, repo_path, config): ...
    async def code_graph(self) -> CodeGraph        # CodeGraph.open, cached
    async def retriever(self) -> Retriever          # built from EmbedConfig + RetrieveConfig
    async def repomap(self) -> RepoMap
    async def status(self) -> dict                  # meta.json + git HEAD staleness + counts
    serve: ServeConfig                              # clamps
```

`status()` reads `.ckg/meta.json` (`schema_version`, `indexed_commit`) and
compares `indexed_commit` to current git HEAD → `dirty: bool`; plus node/edge
counts and `tool_api_version`. Read-only — a tool **never** triggers an index
(spec §4.2); `--refresh-on-call` is parsed but a no-op at 0.1 (feat-004 owns
cheap refresh) and reported as `refresh: "unsupported"`.

### 4.3 The six tools (`tools.py`)

Each is a `Tool` subclass holding the shared `_Engine`; `run` clamps params,
calls feat-006/007, returns a JSON string (or text for the map). Names &
schemas **locked at 0.1**.

| Tool | input_schema | returns |
|---|---|---|
| `ckg_repo_map` | `budget_tokens:int=2000, focus:list[str]=[]` | rendered map (text) |
| `ckg_search` | `query:str, k:int=8, mode:Mode="context"` | `ContextPack.to_dict()` JSON |
| `ckg_symbol` | `symbol_id:str="", name:str="", path:str=""` | definition pack JSON |
| `ckg_impact` | `symbol_id:str, depth:int=1` | reverse-dep pack JSON |
| `ckg_neighbors` | `symbol_id:str, edge_kinds:list[str]=[], depth:int=1` | typed neighbor list JSON |
| `ckg_status` | (none) | status JSON |

- `ckg_search` → `retriever.retrieve(query, k=clamp(k), mode)`; `ckg_impact`
  → `mode="impact", depth=clamp(depth)`; `ckg_symbol` → resolve `name+path`
  to a symbol id via `GraphQuery(name, path_prefix)` when `symbol_id` is
  empty, then `mode="definition"`.
- `ckg_neighbors` → `store.adjacent(symbol_id, edge_kinds, "both")` mapped to
  `{src,dst,kind,provenance}` dicts.
- **Guardrails**: `depth`/`k` clamped to `ServeConfig`; when a pack's JSON
  estimate exceeds `response_token_cap`, items are dropped from the tail and a
  `note` is added (never silent). Every result envelope carries
  `indexed_commit` + `dirty` (staleness — spec §8) and a `truncated` flag.
- **Descriptions** are written for LLM tool-choice (when to use which, an
  example chain: search → take a symbol id → impact / neighbors). Tool-choice
  quality is itself tested via the env-gated agent loop.

### 4.4 Dual binding (`__init__.py`, `server.py`)

```python
TOOL_API_VERSION = "1.0"

def code_graph_tools(repo_path=".", config=None) -> list[Tool]:
    engine = _Engine(repo_path, config)
    return [CkgRepoMap(engine), CkgSearch(engine), CkgSymbol(engine),
            CkgImpact(engine), CkgNeighbors(engine), CkgStatus(engine)]

async def serve_mcp(repo_path=".", config=None, refresh_on_call=False) -> None:
    tools = code_graph_tools(repo_path, config)
    server = MCPServer.from_stdio(tools=tools, allowed=tuple(t.name for t in tools),
                                  server_name="ckg")
    await server.serve()
```

`Agent(tools=code_graph_tools("."))` and `ckg serve-mcp` share the exact same
`Tool` instances — no toolset drift.

### 4.5 CLI + config

- `ckg serve-mcp [--repo .] [--config] [--refresh-on-call]` → `asyncio.run(
  serve_mcp(...))`. (The console script is already `ckg`; this adds the
  subcommand. `--repo` not `--path` to match the spec's `serve-mcp --repo .`.)
- `ServeConfig`: `max_depth: 3`, `max_k: 50`, `response_token_cap: 6000`,
  `refresh_on_call: false` (the `serve:` block already in ckg.yaml).

## 5. Alternatives considered

| Option | Why not |
|---|---|
| A separate `ToolDef` registry rendering to MCP + Tool | The AgentForge `Tool` *is already* the MCP tool source (`MCPServer.from_stdio(tools)`); a second abstraction is redundant. One `Tool` def, two call sites. |
| Return dicts and let the framework serialize | MCP coerces via `str()` → Python repr, not JSON. Return `json.dumps(...)` so agents get valid JSON. |
| Put serve in the deterministic engine (framework-free) | It must import `agentforge`/`agentforge-mcp`. serve is the explicit ADR-0001 framework layer; engine stays clean. |
| Let tools trigger indexing on call | Spec §4.2 — agents must not eat a multi-minute index as a tool side effect. Read-only; `ckg_status.dirty` tells the agent to re-index. |
| HTTP/SSE transport now | stdio matches feat-003 one-store-one-repo; HTTP is post-0.1. |

## 6. Migration / rollout

Tool names/params are semver: new tools / new optional params are minor;
renames/removals major. `ckg_status.tool_api_version` lets long-lived MCP
clients detect mismatch. Reserved tools register only when their feature
ships. No persisted-data change.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Tool sprawl | Hard rule: a new tool needs a feature spec naming it (reserved list); prefer params on existing tools. |
| Stale index misleads agents | Every envelope carries `indexed_commit` + `dirty`; descriptions tell agents to surface staleness. |
| Hub-node `depth=10` blows up a response | Clamp `depth`/`k`; `response_token_cap` trims the tail with a note. |
| MCP result coercion (`str()`) mangles structure | Tools emit `json.dumps`; schema-snapshot tests guard the input contracts. |
| Testing a stdio server without flakiness | Drive the `Tool` instances directly + schema snapshots + a server-construction check in CI; the full stdio/agent loop is env-gated. |
| `agentforge` untyped under mypy --strict | Add `agentforge*`/`mcp*` to mypy `ignore_missing_imports` if needed. |

## 8. Open questions (decisions for review)

1. **One `Tool` definition (no separate registry)?** Proposed: **yes** — the
   `Tool` is the MCP source; bind it twice.
2. **Tools return JSON strings?** Proposed: **yes** (MCP `str()`-coercion).
3. **`--refresh-on-call` a no-op at 0.1?** Proposed: **yes** — read-only;
   real refresh is feat-004; reported as `unsupported`.
4. **No layering test on `serve`?** Proposed: **yes** — serve is the framework
   layer (ADR-0001 exception); engine packages keep their layering tests.

## 9. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-12 | One `Tool` def → both `Agent(tools=…)` and `MCPServer.from_stdio` | The Tool is the MCP source; no second abstraction, no drift |
| 2026-06-12 | Tools return `json.dumps(...)` (text for the map) | MCP coerces results via `str()`; JSON stays valid for agents |
| 2026-06-12 | `serve` imports `agentforge`; no layering test | It is the deliberate ADR-0001 framework layer |
| 2026-06-12 | Read-only tools; `--refresh-on-call` = no-op (`unsupported`) at 0.1 | No multi-minute index as a tool side effect; refresh is feat-004 |
| 2026-06-12 | Every envelope carries `indexed_commit` + `dirty` + `truncated` | Staleness + no-silent-caps surfaced to the agent |
| 2026-06-12 | Lazy-opened `_Engine`; tools constructed synchronously | `Agent(tools=code_graph_tools("."))` works inline |

## 10. Chunk plan (the single feat-008 PR)

| Chunk | Commit | Contents |
|---|---|---|
| 0 | `chore(008): serve config` | `ServeConfig`; design accepted |
| 1 | `feat(008): engine holder + status` | `engine.py` (lazy store/retriever/repomap, `status()` w/ staleness) |
| 2 | `feat(008): the six tools` | `tools.py` (schemas + run + guardrails); per-tool run tests on a fixture index |
| 3 | `feat(008): dual binding + serve_mcp` | `__init__.py` (`code_graph_tools`), `server.py` (`serve_mcp`); MCPServer construction test |
| 4 | `feat(008): ckg serve-mcp CLI` | `ckg serve-mcp` subcommand |
| 5 | `test(008): schema snapshots + guardrails (+ live agent loop)` | JSON-schema snapshot per tool, clamp tests, env-gated agent-in-the-loop |
| 6 | `docs(008): impl status + tracker; design accepted; MVP done` | spec status; TRACKER (v0.1 MVP complete); this doc → accepted; README/runbook usage |

## 11. References

- Spec: `docs/features/feat-008-mcp-server-and-tool-api.md`
- ADR-0001 (layering — serve is the framework layer)
- feat-006 (`Retriever`/`ContextPack`), feat-007 (`RepoMap`),
  feat-003 (`Store`/`GraphStore.adjacent`)
- Framework: `agentforge_core.contracts.tool.Tool`,
  `agentforge_mcp.MCPServer.from_stdio`, `agentforge.Agent(tools=…)`
  (agentforge-py / agentforge-mcp 0.2.4)
