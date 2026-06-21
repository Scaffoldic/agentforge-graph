# Getting started 2 — a workspace (many repos / microservices)

> **TL;DR:** list your services in a `workspace.yaml`, `ckg index` each, then
> `ckg serve-mcp --workspace workspace.yaml` serves **the whole org from one MCP
> endpoint** — survey tools fan across every service, and `ckg_services_map` /
> `ckg_trace` show the **cross-service call graph** (who calls whom).
> **Prereqs:** [1 — a single repo](1-single-repo.md) (each member is just a repo).

Use this when you have **several repos / services** and want to query them
together — especially a microservices architecture where services call each other
over HTTP. A federated endpoint draws the edges *between* services that no
single-repo index can see.

## 1. Describe the workspace

Create a `workspace.yaml` listing the member services (paths are relative to the
manifest):

```yaml
# workspace.yaml
workspace: acme-shop
members:
  - name: web
    repo: ./web
  - name: gateway
    repo: ./gateway
  - name: orders
    repo: ./services/orders
  - name: payments
    repo: ./services/payments
```

A runnable example ships in
[`examples/microservices/`](https://github.com/Scaffoldic/agentforge-graph/tree/main/examples/microservices)
(`web → gateway → orders → payments`, spanning JS `fetch`, Python
`httpx`/`requests`, and a contract-first OpenAPI service).

## 2. Index each member

Each member is an ordinary repo — index them as in guide 1 (incremental, no creds
for the structural graph):

```bash
ckg index ./web && ckg index ./gateway \
  && ckg index ./services/orders && ckg index ./services/payments
```

> For a team, build these centrally instead of per-laptop — see
> [3 — a central store](3-central-store.md). A workspace and a central store
> compose: each member's `ckg.yaml` can point at the shared root.

## 3. Serve the whole org from one endpoint

```bash
ckg serve-mcp --workspace workspace.yaml           # stdio (default), or --transport http
```

Wire it into an MCP client once (Claude Code shown):

```bash
claude mcp add acme -- ckg serve-mcp --workspace /abs/path/to/workspace.yaml
```

## 4. What the federated tools do

**Survey tools fan across every service** and tag each result with its `service`:

- `ckg_search` — one natural-language query, ranked hits from **all** services.
- `ckg_routes` / `ckg_decisions` / `ckg_status` — the whole org's routes /
  decisions / freshness in one call (per-service staleness envelope).

**Pinpoint tools take a `service`** to target one member (a symbol id belongs to
one repo): `ckg_symbol`, `ckg_impact`, `ckg_neighbors`, `ckg_explain`,
`ckg_history`, `ckg_repo_map`.

**Cross-service tools** — the payoff of a workspace:

- **`ckg_services_map`** — the org call graph: each service's outbound HTTP calls
  (`requests`/`httpx`, JS `fetch`/`axios`) matched to the route they hit in
  another service, as `from_service → to_service` edges with the handler. Matches
  use path templates and **anchor to a service's OpenAPI spec** when present, so
  even a contract-first service with no framework code is linked.
- **`ckg_trace`** — walk that graph from a service: `downstream` (what it calls —
  data flow) or `upstream` (who calls it — blast radius). *"Trace everything
  `gateway` reaches"* / *"which services break if I change `payments`."*

## 5. Try it on the bundled demo

```bash
cd examples/microservices
for s in web gateway orders payments; do ckg index "$s"; done
ckg serve-mcp --workspace workspace.yaml
```

Then ask your agent to *use `ckg_services_map`* and *`ckg_trace` upstream from
`payments`*. Expected call graph:

```
web ──fetch──▶ gateway ──httpx──▶ orders ──requests──▶ payments   (matched via OpenAPI)
```

## Notes & limits

- Cross-service edges are computed **live** at federation time (member graphs are
  separate stores) — re-index a member and the next call reflects it.
- HTTP client capture covers Python `requests`/`httpx` (incl. session /
  `base_url` client instances) and JS/TS `fetch`/`axios`; gRPC is a follow-up.
- Matching is unique-match-only — an ambiguous call is reported under
  `unresolved`, never guessed.

→ Full tool reference + transports: [using over MCP](../10-using-over-mcp.md).
