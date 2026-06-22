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

## 2. Build the whole workspace in one command (ENH-021)

The write verbs are workspace-aware — point them at the manifest and they build
**every** member. The one command is `ckg build`:

```bash
ckg build --workspace workspace.yaml          # index + embed (where enabled) every member
ckg build --workspace workspace.yaml --enrich # also LLM pattern tags
```

`index`, `embed`, and `enrich` also each take `--workspace` if you want a single
step across the org (`ckg index --workspace workspace.yaml`). Every member is
built with its **resolved config** (workspace `defaults:` + per-member overrides —
see below), and the run ends with a per-member report.

> **Trace it end to end.** Add `--debug` (or `-v` for info, or `--log-level
> debug`) to watch each step — per-member build progress, index counts, the
> embedder used, git clone/fetch. Or set it durably in config: `logging: { level:
> debug }`. Quiet (`warning`) by default; `$CKG_LOG_LEVEL` works too.

Before doing any work, the build **preflights every member** — if a selected
driver's extra isn't installed (or a credential is missing) it refuses up front
with the fix, rather than failing on member 2 of 4. Validate without building via
`ckg doctor --workspace workspace.yaml`.

### Configure once: workspace defaults + per-member overrides (ENH-022/023)

Put shared config in a `defaults:` block in the manifest (or a sibling
`ckg.yaml`); every member inherits it, and a member can override or opt out:

```yaml
# workspace.yaml
workspace: acme-shop
defaults:
  store:
    central_root: ~/.agentforge/ckg     # all members → central, slug-namespaced
  embed:
    driver: bedrock                      # one embedder for the org
members:
  - name: web
    repo: ./web
  - name: vendor-lib
    repo: ./vendor-lib
    embed: false                         # structure-only — no vectors, no creds
```

### Repos by URL (ENH-024)

A member can be a **git/github URL** instead of a local path — the build clones
it (using your existing ssh/credential-helper auth) into a managed,
git-ignored `<workspace>/.checkouts/<slug>` and builds it there:

```yaml
members:
  - name: gateway
    git: git@github.com:acme/gateway.git
    ref: main                            # optional branch/tag/sha pin
```

First build clones (shallow unless `ref` is pinned); later builds fetch and
update. `ckg build --workspace … --no-fetch` builds against the existing checkout
offline. We never handle credentials — `git` uses your ambient auth.

> For a team, build centrally instead of per-laptop — see
> [3 — a central store](3-central-store.md). A workspace and a central store
> compose: set `store.central_root` once in `defaults:` and every member's index
> lands in the shared root under its own slug.

Each member is still an ordinary repo — you can also index one on its own exactly
as in guide 1 (`ckg index ./web`).

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
ckg build --workspace workspace.yaml          # one command: index every member

# inspect the cross-service graph from the terminal (no agent needed):
ckg services-map --workspace workspace.yaml
ckg trace web --workspace workspace.yaml                       # downstream (data flow)
ckg trace payments --workspace workspace.yaml --direction upstream   # blast radius

# …or serve it to an agent:
ckg serve-mcp --workspace workspace.yaml                       # ckg_services_map / ckg_trace
```

Expected call graph:

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
