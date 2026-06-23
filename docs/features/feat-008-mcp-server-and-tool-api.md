# feat-008: MCP server & agent tool API

## Metadata

| Field | Value |
|---|---|
| **ID** | feat-008 |
| **Title** | MCP server & AgentForge tool API |
| **Status** | shipped (9 tools; stdio + streamable-HTTP transports) |
| **Owner** | kjoshi |
| **Created** | 2026-06-11 |
| **Target version** | 0.1.0 |
| **Languages** | python |
| **Module package(s)** | `agentforge_graph.serve` |
| **Depends on** | feat-006, feat-007 |
| **Blocks** | none (this is the MVP exit) |

---

## 1. Why this feature

A knowledge graph nobody's agent can call is a parquet file with
opinions. The survey's clearest packaging trend (research §2.11):
CKGs ship as **MCP servers** so any agent — Claude Code, custom
AgentForge agents — gets graph queries as tools with zero client code
(embedded single-file indexers, schema-driven CKG designs' MCP
servers, agent-oriented code tools' tool layer). This feature is the
serving layer: an MCP server plus native
AgentForge `Tool` wrappers, both thin over feat-006/007.

## 2. Why it must ship in the agent core

- Tool schemas are contracts: names, parameters, and result shapes
  must be versioned with the graph engine, not per consumer.
- The serving layer enforces read-only discipline and budget caps
  (an LLM caller can request `depth=10` on a hub node; the server
  clamps and reports, instead of OOMing the store).
- Dual surface (MCP + AgentForge Tool) from one definition avoids
  the drift of maintaining two toolsets.

## 3. How consumers benefit

- Claude Code user: `claude mcp add ckg -- ckg serve-mcp --repo .`
  → the agent can orient (`ckg_repo_map`), search
  (`ckg_search`), and trace impact (`ckg_impact`) immediately.
- AgentForge agent author: `Agent(tools=[*code_graph_tools(".")])` —
  the graph becomes a native toolset with AgentForge's budget and
  observability rails applied per call.
- Tool results are structured (`ContextPack.to_dict()`), so agents
  can chain: search → take symbol ID → impact → read chunks.

## 4. Feature specifications

### 4.1 User-facing experience

```bash
ckg serve-mcp --repo .                              # stdio MCP server (default)
ckg serve-mcp --repo . --transport http             # streamable-HTTP at :8765/mcp
ckg serve-mcp --repo . --transport http --host 0.0.0.0 --port 9000
```

Two transports, same tools/guardrails:

- **stdio** — the client launches the server as a subprocess
  (`mcpServers` `command`/`args`, or `claude mcp add ckg -- ckg serve-mcp --repo .`).
- **http** — a long-running streamable-HTTP server (mounted at `/mcp` under
  uvicorn) clients reach by `url` (`{"mcpServers": {"ckg": {"url":
  "http://127.0.0.1:8765/mcp"}}}`). Bind `127.0.0.1` by default; front with a
  proxy/TLS for remote access (no built-in auth at 0.1).

```python
from agentforge import Agent
from agentforge_graph.serve import code_graph_tools

agent = Agent(model="anthropic:claude-sonnet-4-6",
              tools=code_graph_tools(repo_path="."))
```

### 4.2 Public API / contract

**Tool set v1 (names and schemas locked at 0.1):**

| Tool | Params | Returns |
|---|---|---|
| `ckg_repo_map` | `budget_tokens?, focus?` | rendered map (text) |
| `ckg_search` | `query, k?, mode?` | ContextPack dict |
| `ckg_symbol` | `symbol_id \| name+path` | definition pack: node, signature, chunks, doc |
| `ckg_impact` | `symbol_id, depth?` | reverse-dependency pack |
| `ckg_neighbors` | `symbol_id, edge_kinds?, depth?` | typed neighbor list |
| `ckg_status` | — | indexed commit, staleness, stats |

Reserved for later features (registered only when the producing
feature ships): `ckg_decisions` (feat-010), `ckg_routes`
(feat-011), `ckg_explain` (feat-012).

All tools are **read-only**. Indexing is CLI/API only — an agent
must not trigger a multi-minute index as a side effect of a tool
call (explicit `--refresh-on-call` opts into cheap feat-004
refreshes, capped at a wall-clock budget, reported in the result).

### 4.3 Internal mechanics

- Single tool registry (`ToolDef`: name, params model, handler,
  description) renders to both MCP (`mcp` Python SDK over **stdio or
  streamable-HTTP**, via the framework `MCPServer.from_stdio`/`from_http`)
  and AgentForge `Tool` ABC instances. One definition, every binding.
- Server opens the store read-only (feat-003), holds it for the
  process lifetime, and answers `ckg_status` from `meta.json` so
  agents can detect staleness and tell the user to re-index.
- Guardrails: `depth` clamped to 3, `k` to 50, response size to a
  configurable token cap with explicit truncation notes (feat-006's
  no-silent-caps rule carried through).
- Descriptions are written for LLM consumption (when to use which
  tool, example flows) — tool-choice quality is a feature, tested in
  §7.

### 4.4 Module packaging

`agentforge_graph.serve` — default install. `ckg serve-mcp`
console-script entry point.

### 4.5 Configuration

```yaml
serve:
  transport: stdio       # stdio | http (streamable-HTTP at /mcp); --transport overrides
  host: 127.0.0.1        # http bind host
  port: 8765             # http port
  max_depth: 3
  max_k: 50
  response_token_cap: 6000
  refresh_on_call: off
```

## 5. Plug-and-play & upgrade story

Tool names/params follow semver: new tools and new optional params
are minor; renames/removals major. `ckg_status` reports the tool-API
version so long-lived MCP clients can detect mismatch.

## 6. Cross-language parity

n/a (MCP is the cross-language surface).

## 7. Test strategy

- Contract: JSON-schema snapshot tests for every tool (drift fails
  CI).
- Integration: spawn the MCP server against a fixture index; drive
  the six tools over stdio; assert pack shapes and read-only-ness
  (no store mutation).
- Guardrail: hub-node `depth=10` request → clamped, truncation note
  present, bounded latency.
- Agent-in-the-loop (env-gated live): scripted AgentForge agent with
  the toolset answers 5 fixture questions; assert correct tool
  sequence and grounded answers.

## 8. Risks & open questions

| Risk / Question | Mitigation / Decision |
|---|---|
| Tool sprawl (every feature wants a tool) | Hard rule: new tools require a feature spec naming them (reserved list above); prefer params on existing tools |
| Stale index silently misleads agents | Every result envelope carries `indexed_commit` + `dirty: bool`; descriptions instruct agents to surface staleness |
| stdio server per repo vs one server many repos | Per-repo at 0.1 (matches feat-003 one-store-one-repo); revisit with federation |
| Streaming large packs over MCP | Response cap + pagination params post-0.1 if needed |

## 9. Out of scope

- Write tools (annotating the graph from agents) — needs a
  provenance/authz story; post-1.0.
- HTTP/REST API and web UI.
- Auto-indexing daemon (watch mode — see feat-004 §8).

## 10. References

- Research §2.8 (agent-oriented code tools' tool layer), §2.11
  (MCP packaging trend), §5 item 8.
- agentforge-py feat-004 (Tool ABC), feat-013 (MCP integration) —
  framework rails reused here.
- feat-006, feat-007 (the wrapped engines).

---

## Implementation status

**Shipped — v0.1 MVP exit** (Python). Design:
`docs/design/design-008-mcp-server-and-tool-api.md` (accepted).
`agentforge_graph.serve` ships:

- **The six v1 tools** (`ckg_repo_map`, `ckg_search`, `ckg_symbol`,
  `ckg_impact`, `ckg_neighbors`, `ckg_status`) as AgentForge `Tool`
  subclasses over a shared lazy `_Engine`. Read-only; clamp `depth`/`k` to
  `ServeConfig`; return JSON (text for the map) with an
  `indexed_commit`+`dirty`+`truncated` envelope; `response_token_cap` trims
  tails with a note.
- **One definition, two bindings**: `code_graph_tools(repo)` for
  `Agent(tools=…)` and `serve_mcp(repo)` (`MCPServer.from_stdio`, the same
  `Tool` instances). **`ckg serve-mcp`** console entry.
- `agentforge-mcp[mcp]` base dep (the official `mcp` SDK).
- ~98% coverage; per-tool JSON-schema snapshot (drift fails CI); guardrail +
  reopen tests; env-gated agent-in-the-loop (`CKG_LIVE_AGENT`). `mypy
  --strict`, ruff.

This package is the deliberate ADR-0001 **framework layer** (it imports
`agentforge`/`agentforge-mcp`); the engine packages stay framework-free.

**Reserved tools** register when their feature ships: `ckg_decisions`
(feat-010), `ckg_routes` (feat-011), `ckg_explain` (feat-012). **Deferrals**:
write tools, HTTP/SSE transport, auto-index daemon. A LanceDB reopen bug in
feat-003 (paginated `list_tables()`) was found and fixed here.

**v0.1 MVP is complete**: `ckg index . && ckg embed . && ckg query …`, and
`claude mcp add ckg -- ckg serve-mcp --repo .`.
