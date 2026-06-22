# Theme: AgentForge Graph as org-level central code knowledge

> **North star.** CKG is not only a single-developer, single-repo tool. The
> target is a **central, org-wide code knowledge graph** — one queryable brain
> that spans every repo and service an organization owns, hosted centrally, and
> served to **both developers and their agents** over MCP. This theme groups the
> enhancements that carry us from "indexes my one repo on my laptop" to "is my
> org's shared code knowledge."

This is a roadmap *theme*, not a single spec. It frames the **why** behind a
ladder of enhancements so each is read against the same goal rather than as an
isolated ergonomic tweak. Two arcs:

- **Serve/consume side (0.5, done):** ENH-018 · ENH-019 · ENH-020 — host the
  knowledge centrally and serve the whole org over one federated MCP endpoint.
- **Build/setup side (0.6 epic, proposed):** ENH-022 · ENH-021 · ENH-023 ·
  ENH-026 · ENH-024 — stand up that knowledge from **one manifest, one config,
  one command**, with fail-fast validation and (optionally) repos by git URL.

## Why org-level, not just per-developer

The differentiated value of a code knowledge graph compounds with scope:

- **One repo** answers "what calls this function?"
- **One org** answers "if I change this gateway contract, which of our 14
  services break, who owns them, and what architecture decision governs the
  change?" — a question no single-repo index can answer.

We already build for this: the first-party **server backends** (Neo4j +
pgvector, and especially **SurrealDB** — graph + vectors in one server, see
ENH-010) exist precisely so the knowledge can live **centrally** — built once by
a team/CI, hosted on shared infra, and consumed read-only by many developers and
agents. The embedded Kuzu + LanceDB default is the *laptop* story; the server
backends are the *org* story. What's missing is the connective tissue around
them.

## The two audiences

Every rung must serve **both**:

- **Developers** — `ckg query`, `ckg map`, `ckg routes` against the org graph
  from any repo, without standing up their own index.
- **Agents** — the same knowledge over **MCP**, so an agent working in any
  service can reach the whole org's structure, contracts, and decisions. This is
  where the central graph pays off most: an agent that can trace a request across
  service boundaries is qualitatively more useful than one boxed into a single
  repo.

## The ladder

Today's baseline (grounded in code):

- `.ckg` artifacts are resolved **per repo**: `Store.open` computes
  `root = Path(repo_path) / store.path` (`store/facade.py:44`).
- The MCP server serves **exactly one** graph: `serve_mcp(repo_path, …)` →
  `code_graph_tools(repo_path)` → one lazily-opened `_Engine`
  (`serve/server.py:29,93`). One server = one repo.
- A consumer must name the repo explicitly (`--repo`); there is no
  discovery and no cross-repo search.

The rungs that close the gap:

| Rung | Enhancement | What it unlocks | Effort |
|---|---|---|---|
| 1 | **[ENH-018](ENH-018-store-location-and-central-hosting.md)** — store-location choice + central hosting + read-only consumers | Decouple *where knowledge lives* from the repo. A team/CI builds the index once (embedded-but-central, or a shared SurrealDB/Neo4j); devs & agents consume it. The developer **choice**: in-repo (laptop) vs. central (org). | S–M |
| 2 | **[ENH-019](ENH-019-serve-mcp-workdir-autodiscovery.md)** — `serve-mcp` working-directory auto-discovery | Zero-config consumption: an agent or dev *inside* a repo gets the right knowledge without naming `--repo`. Friction that's trivial at one repo and painful across an org's many. | S |
| 3 | **[ENH-020](ENH-020-federated-multi-repo-mcp.md)** — federated multi-repo MCP + cross-service contract edges | The payoff: **one** MCP endpoint serves the whole org, fans queries across every service's graph, and draws the **cross-service edges** (API contracts: route ↔ HTTP/gRPC client) that make a microservice architecture actually traceable. | L (phased) |

### The build/setup arc (0.6 epic)

ENH-018/019/020 nailed *consuming* a central, federated graph. This arc nails
*building* it — turning the nine-hand-commands setup into one manifest-driven
flow. Rungs (sequenced):

| Rung | Enhancement | What it unlocks | Effort |
|---|---|---|---|
| A | **[ENH-022](ENH-022-workspace-config-cascade.md)** — workspace config cascade | Configure store location / embedder / read-only **once** at the workspace; members inherit it (per-member override). The home for cloned-repo config. | M |
| B | **[ENH-023](ENH-023-per-member-embed-toggle.md)** — per-member embed toggle | Declarative `embed: true/false` per repo so the build knows what to vectorize (and what needs no creds). | S |
| C | **[ENH-026](ENH-026-config-preflight-fail-fast.md)** — fail-fast preflight + `ckg doctor` | Validate the consumer's config *before* any work — driver installed? creds present? — and teach the fix. All-at-once across a workspace. | S–M |
| D | **[ENH-021](ENH-021-workspace-build-commands.md)** — workspace build commands | `ckg build --workspace` (and `--workspace` on index/embed/enrich) builds every member in one command, with a per-member report. | M |
| E | **[ENH-024](ENH-024-remote-repo-sources.md)** — remote repo sources | A member can be a **git/github URL** (operator's ssh access); the build clones/fetches into a managed checkout. Build the org graph from a list of URLs. | L |

Dependencies: A → D (build needs the resolved per-member config); B and C feed D;
E lands last (proven on local paths first). **[ENH-025](ENH-025-voyage-embedder.md)**
(Voyage embedder) is adjacent but **deferred** — raised upstream with agentforge-py
first, implemented our end afterward.

## The developer choice we are explicitly offering

A recurring design value here is **not forcing a topology**. The same engine
must serve:

- the solo developer who wants `.ckg` in their one repo, gitignored, zero infra;
- the team that hosts a **central** index (shared dir, or SurrealDB/Neo4j) built
  by CI and consumed read-only;
- the org running **microservices** that wants one federated MCP endpoint with
  cross-service tracing.

ENH-018/019/020 are the configuration and serving surfaces that make all three a
choice rather than a fork.

## Sequencing & dependencies

- **ENH-018 and ENH-019 are independent and small** — ship either first; both are
  pure config/serving ergonomics with no engine-core change.
- **ENH-020 builds on both**: federation consumes multiple stores (ENH-018's
  central/multi-store addressing) and benefits from discovery (ENH-019). Its
  cross-service contract edges extend the **pass-2 resolve** rail from ENH-011
  (intra-repo cross-file) to **cross-repo**.
- None require breaking changes; all are additive (config keys, new serve modes,
  additive node/edge kinds).

## Out of scope (named so we don't scope-creep)

- Multi-tenant auth/RBAC on the central graph beyond the existing HTTP bearer
  token (ENH-005). Org deployments will want per-team scoping — a **separate**
  future enhancement, noted here so ENH-020 doesn't silently absorb it.
- Incremental **distributed** index builds (CI sharding per repo into one central
  store). ENH-018 enables a central store; orchestrating who writes to it at
  scale is follow-on ops work.
