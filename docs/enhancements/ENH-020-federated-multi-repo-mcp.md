# ENH-020: federated multi-repo MCP + cross-service contract edges

| Field | Value |
|---|---|
| **ID** | ENH-020 |
| **Value/Impact** | High (the org-level payoff — one endpoint, the whole org's code brain) |
| **Effort** | L (phased: C-lite federation → C-full contract edges) |
| **Status** | proposed |
| **Area** | `serve` (federation), `frameworks` (cross-repo pass-2), new `workspace` config |
| **Relates to** | [THEME: org-central-knowledge](THEME-org-central-knowledge.md), ENH-011 (cross-file resolve), ENH-018 (central stores), ENH-019 (discovery), feat-011 (frameworks) |

> **One-liner.** Serve the **whole org from one MCP endpoint**: a federated
> server that mounts N repo/service graphs, fans each tool call across them, and
> — the differentiator — draws the **cross-service edges** (API contracts:
> route ↔ HTTP/gRPC client) that make a microservice architecture traceable, not
> just N isolated indexes.

## Motivation

The single highest-value question a code knowledge graph can answer is the one no
single-repo index can: *"if I change this gateway's `/v1/orders` contract, which
downstream services break, who owns them, and what decision governs it?"*

In a microservices org, services don't link via `import` — they link via **API
contracts**: an HTTP/gRPC **client call** in service A targets a **route** in
service B. The intra-repo graph holds both endpoints but never draws the edge
between them, because there is no source-level reference across the repos.
Drawing that edge is exactly the cross-file resolution we shipped *within* a repo
(ENH-011), extended **across** repos. That is the feature that turns "N indexes"
into "an org code brain."

## Current behavior

- One MCP server serves **one** graph. `serve_mcp(repo_path, …)` builds the
  toolset from a single lazily-opened engine:
  ```python
  tools = code_graph_tools(repo_path, config)   # serve/server.py:71
  # → [tool_cls(_Engine(repo_path, config)) for tool_cls in ALL_TOOLS]  (:29-35)
  ```
  Every `ckg_*` tool (`ckg_search`, `ckg_impact`, `ckg_routes`, …) reads that one
  `_Engine`.
- To cover three services today you register **three** MCP servers; an agent must
  call each separately and there is **no graph join** — no way to ask "trace this
  request across services."
- The framework **pass-2 `resolve`** rail (ENH-011) composes route prefixes and
  grounds DI **within a repo**, reading only the persisted graph. It is globally
  idempotent. The cross-repo case is the same shape with a different scope.

## Proposed change — phased

### A workspace manifest (shared by both phases)

A `workspace.yaml` lists the member services and where their graphs live (local
`.ckg`, ENH-018 central subdirs, or server namespaces):

```yaml
# workspace.yaml
workspace: acme-platform
members:
  - name: gateway     ; repo: ./gateway        # or central_root key / server ns
  - name: orders      ; repo: ./services/orders
  - name: payments    ; repo: ./services/payments
```

`ckg serve-mcp --workspace workspace.yaml` serves all members from one endpoint.

### Phase C-lite — federation (moderate effort)

One MCP server, N engines, **no new edges**:

- New `serve.federation`: build **one `_Engine` per member** and a
  **`FederatedEngine`** that holds them keyed by member name.
- Each `ckg_*` tool becomes federation-aware: it accepts an optional
  `service` arg (target one member) and, when omitted, **fans the call across all
  members** and merges results, tagging every hit with its `service`. `ckg_search`
  returns the union ranked together; `ckg_impact` runs per-member; `ckg_routes`
  lists all services' routes with a `service` column.
- The staleness envelope becomes per-member (each member's index commit +
  behind-HEAD), so an agent sees which service's knowledge is stale.

This alone delivers "one endpoint, ask across the whole org" — agents stop
juggling three servers. It draws **no** cross-service edges yet.

### Phase C-full — cross-service contract edges (the differentiator)

Extend the ENH-011 **pass-2 resolve** rail from intra-repo to **cross-repo**,
run by the federated layer over the union of member graphs:

1. **Pass-1 already (mostly) gives us the endpoints.** Routes are extracted today
   (feat-011, 11 packs). We additionally record **outbound client calls** as
   facts: an HTTP client call (`httpx.get("/v1/orders")`, `fetch('…')`,
   `requests.post`, a gRPC stub call) → a `ServiceCall` marker node with
   `attrs = {method, url_template/target, framework}`, riding the caller file's
   FileSubgraph (same pattern as `ROUTE_MOUNT` in ENH-011). Per-pack capture;
   conservative.
2. **Pass-2 cross-repo stitch.** Over the federated graph, match each
   `ServiceCall` to a `Route` in **another member** by `(method, path-template)`
   — normalizing path params (`/v1/orders/{id}` ≡ `/v1/orders/:id`). Emit a new
   **`CALLS_SERVICE`** edge (`ServiceCall → Route`, `attrs = {via: "http"|"grpc",
   confidence}`). **Unique-match-only** (ADR-0004): ambiguous or external targets
   stay unresolved and are reported, never guessed.
3. **Optional contract anchoring.** When an **OpenAPI/proto** file is present,
   prefer matching against the declared contract (operationId / service.method)
   over string-matching URLs — higher precision, and it grounds both ends to the
   spec.

Now `ckg_impact` on a gateway route can traverse `CALLS_SERVICE` to reach
downstream handlers, and a new `ckg_trace` tool can walk a request across service
boundaries.

## Implementation sketch

Grounded in `serve/server.py` and the ENH-011 pass-2 rail:

- **Federation** lives entirely in `serve/` — `FederatedEngine` wraps
  `{name: _Engine}`; `code_graph_tools` gains a federated constructor; tools learn
  an optional `service` arg + merge. **No engine-core change** for C-lite.
- **ServiceCall capture** is per-pack pass-1 (new query captures), additive
  `NodeKind.SERVICE_CALL` — rides feat-004 incrementality like every other
  parsed fact.
- **Cross-repo stitch** reuses `FrameworkExtractor.resolve`'s clear-and-rebuild
  discipline but operates on the **federated** union; `CALLS_SERVICE` is an
  additive `EdgeKind`. Globally idempotent → re-runs are stable.
- Both new kinds are **additive enum values** — no index migration (ADR-0006).

## Surfaces

- `ckg serve-mcp --workspace workspace.yaml` — one federated MCP endpoint.
- Every `ckg_*` tool: optional `service` filter; results carry `service`.
- New `ckg_services_map` (org topology: who calls whom) and `ckg_trace`
  (request path across services) — C-full.
- `IndexReport`/a workspace report: `service_calls_extracted`,
  `cross_service_edges_resolved`, per-member staleness.

## Suggested chunk plan (one branch, multiple commits)

1. `workspace.yaml` schema + loader; `FederatedEngine` (N engines, by name).
2. C-lite: federation-aware `ckg_search`/`ckg_impact`/`ckg_routes` (fan + merge +
   `service` tag); per-member staleness envelope; `--workspace` on `serve-mcp`.
3. `SERVICE_CALL` pass-1 capture for one stack (e.g. Python `httpx`/`requests`).
4. C-full: cross-repo pass-2 stitch → `CALLS_SERVICE` (string-match, unique-only)
   + `incremental == full` over the federated union.
5. OpenAPI/proto contract anchoring (precision upgrade).
6. `ckg_trace` + `ckg_services_map` surfaces.

## Acceptance criteria

- C-lite: one endpoint answers `ckg_search`/`ckg_routes` across 3 services with
  results tagged by service; per-member staleness shown.
- C-full: a gateway route that calls an orders route yields a `CALLS_SERVICE`
  edge; `ckg_impact` on the orders contract surfaces the gateway caller;
  ambiguous/external calls are reported unresolved, **not** mis-linked.
- Re-running resolve is idempotent (federated `incremental == full`).

## Notes / alternatives / risks

| Risk | Mitigation |
|---|---|
| URL string-matching is noisy (path params, base URLs, versioning) | Normalize path templates; prefer OpenAPI/proto anchoring when present; unique-match-only + report unresolved (ADR-0004) |
| Dynamic/computed URLs | Capture + count, never guess (same discipline as dynamic routes today) |
| Federation latency (fan across N engines) | Engines open lazily and run concurrently; `service` filter scopes when the caller knows the target |
| Auth/RBAC across an org graph | Out of scope (named in THEME) — beyond ENH-005's bearer token; a separate enhancement |
| Member graphs out of sync | Per-member staleness envelope makes it visible to the agent |

## Candidacy

The flagship of the org-central theme — **0.5/1.0 territory** given the L effort.
Sequence: land **ENH-018** (central stores) and **ENH-019** (discovery) first,
then **C-lite** federation (immediately useful, moderate), then **C-full**
contract edges (the differentiator). Each phase ships independently.
