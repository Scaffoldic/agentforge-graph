# Using the CKG from an agent (MCP) or in-process

agentforge-graph exposes a repo's Code Knowledge Graph to **any agent or
developer** two ways, over the **same 10 read-only tools** and the same engine:

1. **MCP server** — for external clients (Claude Code, Cursor, any MCP host), over
   **stdio** (subprocess) or **HTTP** (streamable-HTTP at a URL).
2. **In-process AgentForge toolset** — for agents built on the framework.

Both are read-only, per-repo, and need no network service — the graph lives in an
embedded store under `.ckg/` (feat-008 / ADR-0006).

---

## 1. Prepare the repo (one-time, then incremental)

The server reads a prebuilt store; it does **not** index on startup.

```bash
ckg index .     # build the graph (files/symbols/calls/imports, +ADRs/routes)
ckg embed .     # vectors for semantic search  (needed only for ckg_search)
ckg enrich .    # optional: design-pattern tags + summaries (powers ckg_explain)
```

Re-running is incremental (feat-004). Minimum to serve: `ckg index .`. Without
`ckg embed`, every tool works **except** `ckg_search` (which needs vectors).

---

## 2a. Serve over MCP (external agents)

Two transports, **same 10 tools and guardrails** — pick by how the client connects.

### stdio — client launches a subprocess (simplest, local)

```bash
ckg serve-mcp --repo .            # blocks; --config <ckg.yaml> optional
```

**Claude Code**:

```bash
claude mcp add ckg -- ckg serve-mcp --repo /abs/path/to/repo
```

**Any MCP host** (Cursor, Claude Desktop, custom) via a `command`/`args` block:

```json
{
  "mcpServers": {
    "ckg": {
      "command": "uv",
      "args": ["run", "ckg", "serve-mcp", "--repo", "/abs/path/to/repo"]
    }
  }
}
```

The client owns the process lifetime; scoped to one repo.

### http — a long-running server clients reach by URL

```bash
ckg serve-mcp --repo . --transport http                 # → http://127.0.0.1:8765/mcp (localhost, no auth)
export CKG_HTTP_AUTH_TOKEN=$(openssl rand -hex 32)      # exposed port → require a token
ckg serve-mcp --repo . --transport http --host 0.0.0.0 --port 9000
```

Connect by **`url`** (streamable-HTTP, mounted at `/mcp`), sending the token as a
bearer header:

```json
{
  "mcpServers": {
    "ckg": {
      "url": "http://your-host:9000/mcp",
      "headers": { "Authorization": "Bearer <CKG_HTTP_AUTH_TOKEN>" }
    }
  }
}
```

Use http when the server should outlive the client, be shared by several
agents/clients, or run on another host/container. Defaults bind `127.0.0.1`.

**Auth (ENH-005):** set a **bearer token** — `serve.http_auth_token` in `ckg.yaml`
or, preferably, `$CKG_HTTP_AUTH_TOKEN` — and every request must carry a matching
`Authorization: Bearer …` (others get `401`; the token is never logged). It's
**off by default** so the localhost loop needs nothing. Binding a **non-loopback**
host (`0.0.0.0`) with no token is **refused** unless you pass
`--allow-unauthenticated` — an exposed port is never silently wide open. For
public/multi-tenant exposure, still front it with TLS + a proxy; the token makes
the *simple* secure deployment need no extra infrastructure. stdio needs no auth
(the client owns the subprocess). Run one server per repo.

Either transport can be set as the default in `ckg.yaml` (`serve.transport`,
`serve.host`, `serve.port`, `serve.http_auth_token`); the CLI flags override it.

## 2b. Use in-process (AgentForge agents)

Same tools, no subprocess — hand them to an `Agent`:

```python
from agentforge import Agent
from agentforge_graph.serve import code_graph_tools

agent = Agent(model="anthropic:claude-sonnet-4-6", tools=code_graph_tools("."))
answer = await agent.run("Which functions call `validate_token`? Use the ckg tools.")
```

The agent tool-chooses and chains (e.g. `ckg_search` → take a `symbol_id` →
`ckg_impact`) on its own.

---

## 3. The tools (all read-only, v1 API)

| Tool | What it answers | Key inputs (required **bold**) |
|---|---|---|
| `ckg_repo_map` | "Get me oriented" — centrality-ranked, budget-bounded map | `budget_tokens` (2000), `focus[]` |
| `ckg_search` | "Find code relevant to this question" — ranked **connected** context | **`query`**, `k` (8), `mode` (`context`) |
| `ckg_symbol` | "Show this symbol's definition, chunks, members" | `symbol_id` *or* `name`+`path` |
| `ckg_impact` | "Who depends on this?" — reverse CALLS/IMPORTS/IMPLEMENTS | **`symbol_id`**, `depth` (1) |
| `ckg_neighbors` | "Typed graph neighbours" — both directions, filterable | **`symbol_id`**, `edge_kinds[]`, `depth` (1) |
| `ckg_status` | "Index commit, staleness, node counts, API version" | — |
| `ckg_routes` | "HTTP API surface" — method/path/handler (feat-011) | `method`, `path` |
| `ckg_decisions` | "ADRs governing this code" — status/date/governed symbols | `scope`, `status` |
| `ckg_explain` | "Design-pattern tags + 1-hop facts for a symbol" | **`symbol_id`** |
| `ckg_history` | "When/who/churn for a symbol; what changed since a ref" (feat-009) | `symbol_id`, `since` |

`ckg_repo_map` returns rendered text; the rest return JSON.

### Every JSON result carries provenance + freshness

```jsonc
{
  "indexed_commit": "a1b2c3d",   // commit the graph was built at
  "dirty": false,                // HEAD has drifted from indexed_commit
  "truncated": false,            // response was cut to fit the token cap
  "tool_api_version": "1.0",
  "items": [ /* ... */ ]
}
```

So a consuming agent can tell whether the answer is stale (`dirty: true` → suggest
a re-`index`) and whether it saw the full result set (`truncated: true`).

---

## 4. Guardrails (`serve:` block in `ckg.yaml`)

Tool responses are bounded so an agent can't blow its context:

| Key | Default | Effect |
|---|---|---|
| `max_depth` | 3 | clamps `ckg_impact` / `ckg_neighbors` traversal depth |
| `max_k` | 50 | clamps `ckg_search` result count |
| `response_token_cap` | 6000 | drops tail items until the response fits; sets `truncated: true` |
| `refresh_on_call` | false | (0.1: no-op) |

Clamping is **explicit** — never silent. When a limit bites, the envelope says so.

---

## 5. A typical agent flow

1. `ckg_status` → confirm the graph is fresh (`dirty: false`).
2. `ckg_repo_map` → orient in an unfamiliar repo.
3. `ckg_search("how are auth tokens validated")` → ranked connected context.
4. take a returned `symbol_id` → `ckg_impact` ("what breaks if I change this")
   or `ckg_explain` ("what is this, and what governs it").

See also: [`model-providers.md`](model-providers.md) (which models power
`ckg_search`/`ckg_explain`) and the feat-008 spec for the tool contract.
