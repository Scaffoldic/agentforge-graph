# Changelog

All notable changes to **agentforge-graph** are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/), and the project aims to
follow [Semantic Versioning](https://semver.org/). Until 1.0 the on-disk index
schema may change between minor versions — the index is derivable, so the policy
on a schema mismatch is **rebuild** (ADR-0006).

## [Unreleased]

## [0.5.0] — 2026-06-21

The **org-level central knowledge** release — take CKG from "indexes my one repo"
to "is my org's shared code brain": host the index **centrally** and consume it
**read-only**, serve a multi-repo **workspace** from one federated MCP endpoint,
and **trace requests across services** (HTTP client → route, matched by path or
OpenAPI contract). (Also: the scaffold template was upgraded to AgentForge 0.3.1.)

### Added

- **`ckg services-map` and `ckg trace` CLI commands** (ENH-020). The cross-service
  call graph and request tracing — previously MCP-only — are now on the command
  line: `ckg services-map --workspace workspace.yaml` prints `from → to` edges
  (with handler + `via`), and `ckg trace <service> --workspace …
  [--direction downstream|upstream] [--depth N]` walks the graph (data flow /
  blast radius). See the org topology from a terminal, not just an agent.
- **Microservices demo + end-to-end test** for the org-central features. A
  bundled `examples/microservices` workspace (web→gateway→orders→payments,
  spanning JS `fetch`, Python `httpx`/`requests`, and a contract-first OpenAPI
  service) with a runnable walkthrough, plus an automated e2e test that exercises
  ENH-018 (central hosting + read-only), ENH-019 (cwd discovery) and ENH-020
  (federation + `ckg_services_map` + `ckg_trace`) in one flow — the demo is the
  test fixture, so they can't drift.
- **OpenAPI contract anchoring for the cross-service map** (ENH-020 C-full). When
  a member ships an OpenAPI/Swagger spec (`openapi.{json,yaml,yml}` /
  `swagger.{json,yaml}` at the repo root), `service_map` now matches calls against
  the **declared contract** too — giving authoritative paths, the `operationId` as
  the handler, and coverage for **contract-first services with no detected
  framework**. A framework route and its spec twin are deduped (param-agnostic) so
  they never make a call ambiguous; each edge reports its `via` (`framework` |
  `openapi`). Precision + coverage upgrade over URL-string matching alone.
- **JS/TS cross-service calls (fetch / axios)** (ENH-020 C-full). A new
  `jshttpclient` pack (spanning `.js` + `.ts`) captures `fetch("…")`,
  `axios.get("…")` / `axios.post("…")` and `axios("…")` as `ServiceCall` nodes —
  `fetch`'s method read from a literal `{ method: "POST" }` option, default GET.
  So a JS/TS frontend or BFF now appears as a caller in the cross-service map /
  `ckg_services_map` / `ckg_trace`, not just Python services.
- **HTTP client coverage: instance clients + `base_url`** (ENH-020 C-full). The
  `httpclient` pack now also captures calls through a client *instance* —
  `s = requests.Session(); s.get(…)` and `c = httpx.Client(base_url="http://orders");
  c.get("/v1/x")` — composing `base_url + path` into the matched URL. This is the
  dominant real-world pattern (previously only module-qualified `requests.get(…)`
  with a literal URL was seen), so the cross-service map covers far more actual
  calls. Still conservative: dynamic URLs are counted, not guessed.
- **`ckg_trace` — walk a request across services** (ENH-020 C-full). From a
  starting service, trace the cross-service call graph `downstream` (what it
  calls — data flow) or `upstream` (who calls it — blast radius), to a depth.
  Returns the reachable hops (with hop numbers) and the services reached; cycles
  terminate. Turns the `ckg_services_map` edges into the answer to *"what does
  this service depend on / which services break if I change it"* — impact
  analysis that spans service boundaries. Federation-only tool.
- **Cross-service call graph** (ENH-020, C-full increment 2). The federated MCP
  server now draws **who-calls-whom across services**: it matches each member's
  outbound `ServiceCall` to a `Route` in *another* member by `(method, path)` —
  with path-parameter awareness (`{id}` / `:id` / `<id>`) — and exposes the org
  call graph via a new `ckg_services_map` tool (`from_service → to_service`,
  method, path, handler, plus `unresolved` calls). Computed live because member
  graphs are separate stores; unique-match-only (ADR-0004) — an ambiguous call is
  reported, never guessed. This completes the microservices payoff: an agent can
  see the whole org's service topology from one endpoint.
- **Outbound HTTP client calls are captured** (ENH-020, C-full increment 1).
  A new `httpclient` framework pack records module-qualified `requests.get("…")`
  / `httpx.post("…")` calls as `ServiceCall` graph nodes (method + URL + path),
  riding the caller file's subgraph like routes. Surfaced via
  `CodeGraph.service_calls()` and `ckg service-calls`. Conservative (ADR-0004):
  literal URLs only; dynamic URLs / client-instance calls are counted, not
  guessed. This is the **caller side** of a cross-service edge — at federation
  time these match `Route` nodes in other services (the next increment:
  `ckg_services_map` / `ckg_trace`).
- **Federated MCP over a workspace** (ENH-020, C-lite). `ckg serve-mcp
  --workspace workspace.yaml` serves **many member repos/services from one
  endpoint**. The **survey tools** (`ckg_search`, `ckg_routes`, `ckg_decisions`,
  `ckg_status`) fan across every member and tag each result with its `service`
  (with a per-service staleness envelope); the **pinpoint tools** (`ckg_symbol`,
  `ckg_impact`, `ckg_neighbors`, `ckg_explain`, `ckg_history`, `ckg_repo_map`)
  take a `service` to target one member. A single repo is unchanged (no
  `services` envelope). This is the microservices payoff of the
  org-central-knowledge theme — one code brain for the whole org. (Cross-service
  *contract edges* — tracing a request across services — are the next phase,
  C-full.) Also fixes the MCP `_Engine` to honor `store.central_root` (ENH-018).
- **Read-only consumers** (ENH-018). `store.read_only: true` (or `--read-only` /
  `$CKG_READ_ONLY`) makes a store consume-only: the write verbs (`index`,
  `embed`, `enrich`) refuse with a clear message and a non-zero exit, and opening
  a *missing* index errors instead of silently creating one. Read verbs
  (`query`, `map`, `routes`, `serve-mcp`, …) work normally. This is what lets a
  team host one central index (built by CI) and hand it to many developers and
  agents without risk of accidental mutation.
- **Host the index outside the repo with `store.central_root`** (ENH-018).
  By default the index stays in the gitignored `.ckg/` inside the repo (the
  laptop story, unchanged). Set `store.central_root: /shared/ckg` and each repo's
  artifacts move to a stable, **collision-free per-repo subdir** under that root
  — keyed by git remote (`org/repo`, host-independent) or `<dirname>-<hash>` with
  no remote — so a team/CI can build once and host many repos centrally. The
  `.ckg` root is now resolved through one helper (`store.location.resolve_root`),
  de-duplicating ~10 call sites. `ckg status` shows the resolved location
  (`(central)` when hosting is on). First rung of the org-central-knowledge theme.
- **`ckg` now discovers the repo root from the working directory** (ENH-019).
  When no path is given, every subcommand — including `ckg serve-mcp` — walks up
  from the cwd to the nearest `.ckg/` / `agentforge.yaml` / `ckg.yaml` / `.git`
  (nearest wins), like `git`. So a bare `ckg serve-mcp` from anywhere inside a
  repo serves *that* repo — no `--repo` needed — which is what an MCP client
  launching the server in a project directory wants. Falls back to `.` when no
  marker is found (unchanged for a bare directory); an explicit positional /
  `--path` / `--repo` always wins; when discovery climbs above the cwd the
  resolved root is announced on stderr. First rung of the org-central-knowledge
  theme (zero-config consumption).

### Changed

- **Getting-started guides reorganised by setup** into three step-by-step
  walkthroughs — [single repo](docs/guides/getting-started/1-single-repo.md),
  [workspace](docs/guides/getting-started/2-workspace.md), and
  [central store](docs/guides/getting-started/3-central-store.md) — under a hub
  (`01-getting-started.md`, kept so existing links resolve). The 10 topic guides
  are unchanged.
- **README refreshed for the three setups** with a new `docs/assets/setups.gif`
  (single repo → central store → workspace `services-map` / `trace`), rendered by
  `scripts/render-setups-gif.sh`.
- **Scaffold template upgraded to AgentForge 0.3.1** (`agentforge upgrade`); the
  files we own are forked so future upgrades skip them.

## [0.4.0] — 2026-06-20

### Changed

- **Consolidated engine config into `agentforge.yaml` (`app:` section).**
  agentforge-py 0.3.x added a sanctioned `app:` passthrough to its strict config
  file — the fix for the workaround that forced a separate `ckg.yaml`. The engine
  now reads its config from `app:` (or a top-level standalone `ckg.yaml`, still
  supported) using **plain pyyaml, no `agentforge` import** (ADR-0001), and
  **auto-discovers** the file in the repo (previously only `--config` was read).
  One config file. `config.resolve_config()` + `app:`-aware `_read_block`.
- **HTTP MCP auth now rides the framework's `from_http(middleware=)` seam**
  (agentforge-mcp 0.3.x), replacing the `CkgHttpRunner` that reimplemented ~60
  lines of HTTP-serve internals to add a bearer gate. `BearerAuthMiddleware`
  unchanged; verified live (401 / pass-through). (ENH-005.)
- **Upgraded the AgentForge framework pin to `>=0.3,<0.4`** (from the validated
  0.2.x line). Re-validated: the full gate (666 tests / 95%, ruff + mypy) and an
  MCP server-construction smoke pass on `agentforge-py` 0.3.1 — the `Tool` /
  `BudgetPolicy` / `MCPServer` surfaces are unchanged.

### Added

- **Bedrock-native reranker + measurement campaign (ENH-013).** A torch-free
  `BedrockRerankScorer` (AWS Bedrock Rerank API — Cohere Rerank 3.5 / Amazon
  Rerank) behind the existing `CrossScorer` seam, selected via
  `rerank_model: bedrock:cohere.rerank-v3-5:0` — reuses the AWS creds the embedder
  already uses, no `rerank`/torch extra. A two-corpus campaign (harness
  `scripts/rerank_eval.py`, [results](docs/validation/rerank/results.md)) found
  the cross-encoder is an **ordering** win (MRR +10–16% at blend weight 0.3) over
  an already-recall-saturated base, costing ~540 ms/query — so rerank **stays
  opt-in**, with the Bedrock config @ `w=0.3` documented as the recommended
  precision setting. New `retrieve.rerank_region` config. A **rigorous follow-up
  benchmark** (`scripts/rerank_benchmark.py`, objective docstring→code labels,
  388 queries / 4 OSS repos) confirms base retrieval MRR 0.95 / recall@1 0.92 and
  a statistically-significant rerank lift (ΔMRR +0.019, p<0.001) — surfaced in the
  README's "Retrieval quality (measured)" section.

- **Four new framework packs — Go / C# / PHP / Ruby routes (ENH-012).** Framework
  awareness now spans **11 packs** across six languages. Each rides a small new
  `_<lang>_ast` helper and is conservative (ADR-0004); detection uses import
  markers since these languages' deps live outside the scanned manifests.
  - **Gin** (Go) — `r.GET("/x", handler)` method calls → `Route` + `HANDLED_BY`
    to the Go function (mirrors Express).
  - **ASP.NET** (C#) — `[HttpGet("/x")]` attributes on controllers → `Route` +
    `HANDLED_BY` to `Class#method`; `[Route]` base path + `[controller]` token
    (mirrors Spring).
  - **Laravel** (PHP) — `Route::get('/x', [C::class, 'm'])` / `'C@m'` / invokable.
  - **Rails** (Ruby) — `routes.rb` explicit `get '/x' => 'c#a'` / `to:` / `root`.

  Laravel and Rails name their handler in another file, so a new **generic
  cross-file route-handler grounding** pass-2 step (`frameworks/cross_file.py`)
  resolves the controller reference to the real `Class#method` symbol anywhere in
  the repo (unique-match), emitting `HANDLED_BY` — globally idempotent, surfaced
  as `IndexReport.route_handlers_grounded`. ORM models (EF Core / Eloquent /
  ActiveRecord), the ASP.NET minimal API, and the Rails resourceful DSL are
  follow-ups.

- **Cross-file framework resolution — route prefixes + DI grounding (ENH-011).**
  A globally-idempotent pass-2 (`frameworks/cross_file.py`) stitches the
  compose-points real apps split across files, reading only the persisted graph
  (`IMPORTS` edges + node attrs), unique-match-only (ADR-0004):
  - `app.include_router(payments.router, prefix="/api")` composes `/api` onto the
    included router's routes. The base `path` is preserved; the composed URL is a
    new `path_pattern` attr (`RouteInfo.path_pattern`, shown by `ckg routes` and
    returned by the `ckg_routes` MCP tool). New `RouteMount` node kind.
  - `Depends(get_db)` grounds the provider *name* to the `get_db` function symbol
    in its module via a new `PROVIDED_BY` edge (+ `Service.provider_symbol`).

  Ships for **FastAPI**; Flask / Express / Django reuse the same framework-
  agnostic pass-2 (per-pack pass-1 capture pending). New `RouteMount` /
  `PROVIDED_BY` kinds are additive and migration-free (the stores key edges/nodes
  by a `kind` string column). `IndexReport.route_prefixes_composed` /
  `di_providers_grounded`; `incremental == full` preserved. New runbook:
  `docs/guides/04-cross-file-framework-resolution.md`.

- **`CITATION.cff`** — GitHub "Cite this repository" metadata.

- **Consumer feature guides + a runnable example.** New `docs/guides/` for the
  headline features — framework extraction (routes/models/services), architecture
  decisions, temporal/history, enrichment, and an index→query walkthrough — plus
  `examples/fastapi-shop/`, a tiny FastAPI+SQLAlchemy app you can index in one
  command to see routes/models/services (output verified against the CLI).

- **Project metadata + community health.** `[project.urls]` (Homepage,
  Repository, Changelog, Issues, Documentation) so the PyPI page links out;
  `SECURITY.md`, `CODE_OF_CONDUCT.md`, GitHub issue + PR templates; README doc
  links made absolute so they resolve on the PyPI project page.

- **SurrealDB storage backend — graph + vectors in one (ENH-010).** A first-party
  `surrealdb` driver for *both* `store.graph.driver` and `store.vectors.driver`,
  so one multi-model server is a complete backend (`pip install
  agentforge-graph[surrealdb]`). It passes the same `GraphStoreConformance` /
  `VectorStoreConformance` suites as Kuzu/Neo4j/LanceDB/pgvector — verified
  against a live SurrealDB in the `server-backends` CI job. Nodes/edges are
  document tables on the shared open schema (hash-keyed records, the symbol id in
  a `key` field); vector search is brute-force cosine in `[0, 1]`. This makes the
  "day-one, plug in a different DB" promise provable end-to-end against an
  independent third backend.

## [0.3.3] - 2026-06-19

Leaner base install + the refreshed README on PyPI.

### Changed

- **Dropped the unused `fastembed` dependency** from the base install (and the
  heavy `onnxruntime` wheel it pulled). It was a leftover from the original
  feat-005 plan to default to local embeddings; the shipped embedders are
  `bedrock` / `openai` / `fake`, none of which import it. Removing it keeps the
  promise true: the base install carries only what the engine actually uses, and
  every model/DB provider is opt-in. (No local-embeddings driver existed, so
  nothing is lost; a `fastembed` driver behind a `[local]` extra can be added as
  a deliberate feature later.)
- README refreshed (out-of-the-box overview, quick start, demo) now renders on
  the PyPI project page.

## [0.3.2] - 2026-06-19

Packaging fix — base-install completeness (caught on a TestPyPI dry run).

### Fixed

- `pip install agentforge-graph` now works out of the box. The deterministic
  graph engine dependencies (`tree-sitter`, `tree-sitter-language-pack`, `kuzu`,
  `lancedb`, `fastembed`, `networkx`) moved from the optional `engine` extra into
  the base `dependencies` — the package's top-level import chain loads the
  parse/store/embed/repo-map stack, so a bare install previously failed at
  `import agentforge_graph` with `ModuleNotFoundError: No module named 'kuzu'`.
  The `engine` extra is kept as an empty no-op for backward compatibility
  (`pip install agentforge-graph[engine]` still resolves).

## [0.3.1] - 2026-06-19

Packaging release — the **PyPI debut**. No functional changes.

### Packaging

- Add PyPI distribution metadata: `readme` (renders the README on the project
  page), `keywords`, and trove `classifiers`.
- Pin the AgentForge framework dependencies (`agentforge-py`,
  `agentforge-anthropic`, `agentforge-mcp`) to the validated `>=0.2.4,<0.3`
  line, so a fresh `pip install` resolves the framework version this release was
  built and tested against (rather than an unvalidated newer line).

## [0.3.0] - 2026-06-19

The **History + decisions** release, plus the **framework-aware extractors**
differentiator landed early. feat-009 temporal layer (shipped in 0.2.0) +
feat-010 ADR/docs ingestion complete the 0.3 theme; feat-011 adds framework
edge extraction across Python, JavaScript/TypeScript, and Java. The on-disk
index schema is unchanged from 0.2.0 (the new node/edge kinds were reserved at
0.1).

### Added

- **NestJS routes — TypeScript (feat-011).** A built-in NestJS pack extracts
  controller endpoints into `Route` nodes + `HANDLED_BY` edges. A class is a
  route source only with an `@Controller` decorator (its `@Controller('base')`
  arg is the base path); each `@Get`/`@Post`/`@Put`/`@Delete`/`@Patch`/`@All`
  method becomes a route (base joined with the decorator path) handled by the
  `Class#method` symbol. Handles TS's preceding-sibling decorator placement.

- **Spring MVC routes — Java (feat-011).** A built-in Spring pack extracts
  controller endpoints into `Route` nodes + `HANDLED_BY` edges. A class is a
  route source only when it's a controller (`@RestController`/`@Controller` or a
  class-level `@RequestMapping`); each `@GetMapping`/`@PostMapping`/… (or
  `@RequestMapping(method=RequestMethod.X)`) method becomes a route whose path is
  the class base path joined with the method path, handled by the `Class#method`
  symbol. First Java framework extractor.

- **Express routes — JavaScript + TypeScript (feat-011).** A built-in Express
  pack extracts `app.get('/x', handler)` / `router.post('/x', mw, handler)` into
  `Route` nodes. A named handler (the call's last argument) gets a `HANDLED_BY`
  edge to its symbol; an anonymous inline handler still yields the `Route` (with
  `attrs.handler = ""`). `app.use`/`app.listen` and dynamic paths are
  skipped/counted. The pack spans both languages via a new `FrameworkPack.slugs`
  property and builds handler ids with the file's own slug; shared JS/TS
  tree-sitter helpers live in `packs/_js_ast.py`.

- **Flask routes (feat-011).** A built-in Flask framework pack extracts
  `@app.route("/x", methods=[...])` / blueprint `@bp.route(...)` and the Flask
  2.0 shortcuts (`@app.get` …) into `Route` nodes + `HANDLED_BY` edges. A `route`
  decorator defaults to `GET` and emits one route per listed method; class-based
  handlers resolve to `Class#method`; a dynamic (non-literal) path is counted
  unresolved. Shares the route helpers with FastAPI (now in `packs/_python_ast`).

- **Class-based FastAPI handlers & DI consumers (feat-011).** A route decorator
  or `Depends`/`Security` parameter on a *method* now resolves to its
  `Class#method` symbol — `HANDLED_BY` / `INJECTED_INTO` land on the real method
  node — instead of being counted unresolved. Only a dynamic (non-literal) route
  path remains unresolved.

- **FastAPI dependency injection as `Service` / `INJECTED_INTO` (feat-011).** A
  parameter defaulting to `Depends(provider)` / `Security(provider)` becomes a
  `Service` node (the provider) with an `INJECTED_INTO` edge to the consuming
  function — so "what is injected into this handler" and "where is `get_db`
  injected" are graph traversals. Intra-file, module-level consumers (class-based
  consumers counted, not dropped). Surfaced via `CodeGraph.services()`, the
  `ckg services` CLI, and `IndexReport.services_extracted`.

- **Django ORM models (feat-011).** A built-in Django framework pack extracts
  `models.Model` classes into `DataModel` nodes with `HAS_FIELD` columns and
  `RELATES_TO` edges for `ForeignKey`/`OneToOneField`/`ManyToManyField` (kind
  `fk`|`o2o`|`m2m`; FK/O2O also a column, M2M relation-only). Model evidence is a
  `Model`-tail base or any `models.*Field` assignment (catching abstract-base
  subclasses); the table comes from `class Meta: db_table` when set. Relation
  targets (class ref, `"app.Model"` string, or `"self"`) resolve by class name.
  Built on shared ORM rails (`frameworks/orm.py`, `packs/_python_ast.py`) now
  used by both the SQLAlchemy and Django packs.

- **ORM `RELATES_TO` edges from `relationship`/`ForeignKey` (feat-011).** The
  framework pass-2 hook (`FrameworkPack.resolve`) is now wired into the full
  pipeline and the incremental indexer. The SQLAlchemy pack records each
  `relationship("X")` / `ForeignKey("t.c")` string target in pass-1 and stitches
  them into cross-file `RELATES_TO` edges in pass-2 (`attrs.kind` =
  `relationship`|`fk`, `attrs.via` = the field): `relationship` → the model whose
  class is `X`, `fk` → the model whose table matches. Unique-match-only
  (ambiguous class names left unresolved). Globally idempotent — an incremental
  refresh converges to the full-index graph. Surfaced via `ModelInfo.relations`,
  `ckg models`, and `IndexReport.relations_resolved`.

- **SQLAlchemy ORM models as `DataModel` nodes (feat-011).** The built-in
  SQLAlchemy framework pack extracts declarative models into `DataModel` nodes
  (table from `__tablename__`, the underlying class in `attrs.class`) with
  `HAS_FIELD` edges to each mapped column — a `Variable` field carrying its
  `column_type`. Classic (`name = Column(Integer)`) and 2.0-style
  (`id: Mapped[int] = mapped_column()`) forms both recognised; a class becomes a
  model only with declarative evidence (`__tablename__` or ≥1 column), so plain
  classes never mint false models. Surfaced via `CodeGraph.models()`, the
  `ckg models` CLI, and `IndexReport.models_extracted`. (Cross-file
  `relationship`/`ForeignKey` → `RELATES_TO` edges land in the companion entry
  above.)

- **JS/TS JSDoc as `DESCRIBES` doc nodes (feat-010).** A `/** … */` block comment
  immediately before a function/class/method becomes a `DocChunk` that `DESCRIBES`
  the symbol — extending docstring ingestion (Python) to JavaScript/TypeScript. The
  cleaner strips `/** */` markers + per-line `*`; only `/**` blocks count (plain
  `//` / `/* */` comments are ignored). Embedded + retrievable like any DocChunk.
  (Java/C# doc comments, Go/Rust/Ruby/PHP conventions, and module-level docstrings
  remain follow-ups.)

- **Commit-message ingestion (feat-010).** With `knowledge.commit_messages: on`, the
  last `commit_messages_limit` (50) git commit subjects that are conventional commits
  (`feat:`/`fix:`/…) or carry an issue ref (`#123`/`PROJ-45`) become `DocChunk`s that
  `DESCRIBES` the in-repo files they touched — so "why did the retry logic change?"
  reaches the commit and its code. Keyed by sha, added idempotently (re-index skips
  known shas). Read via `git log` (no framework import); off by default.

- **Code-vs-doc retrieval weighting (feat-010).** ADR/doc (`source_type: doc`)
  vector hits are scaled by `retrieve.doc_weight` (default 0.7) so code outranks
  equally-similar prose by default — mitigating doc-volume dilution. When the query
  smells architectural (`why`/`decision`/`design`/`convention`/…) the penalty is
  lifted and docs keep their full score. Applies to both the item score and its
  graph-expansion seed.

- **Incremental doc embedding (feat-010).** The doc-embed pass now fingerprints all
  DocChunks (ids + content hashes + embedder) under `.ckg/doc_embed.hash` and skips
  the whole pass when nothing changed — so `ckg embed` after an incremental refresh
  no longer re-embeds unchanged ADR/doc/docstring prose. Any doc change triggers a
  clean re-embed (orphan-safe for the small doc set).

- **General Markdown docs as `DESCRIBES` nodes (feat-010).** Docs matched by
  `knowledge.doc_globs` (e.g. `["**/*.md"]` — READMEs, guides) are sectioned into
  `DocChunk`s that `DESCRIBES` the code each section unambiguously mentions (a
  repo-relative path or a unique symbol name). No `Decision` node — docs *describe*,
  ADRs *govern*; ADR files are excluded (handled by the ADR pass). Each doc is its
  own per-file subgraph, so edits/deletes ride incremental indexing (with GC of
  removed docs); `IndexReport` gains `docs_indexed`/`describes_resolved`. Empty
  (off) by default.

- **Docstrings as `DESCRIBES` doc nodes (Python, feat-010).** A Python symbol's
  leading docstring (the first body string of a class/function/method) is now
  extracted as a `DocChunk` that `DESCRIBES` the symbol. The docstring prose
  becomes its own searchable node (embedded by the doc-chunk pass, `source_type:
  doc`); a vector hit on it seeds the symbol it describes, so a docstring-prose
  query reaches the code. Carried in the code file's subgraph, so it rides
  incremental indexing; symbols without a leading docstring get nothing. (JSDoc /
  Java-C# doc comments / module docstrings are follow-ups.)

- **`infer_governs` LLM pass for ADRs (feat-010).** An optional, budgeted matcher
  proposes `GOVERNS` edges for decisions whose prose names no code — matching the
  decision text against the repo's candidate symbols and writing edges with honest
  `llm` provenance + confidence + rationale. It only considers decisions with
  **zero parsed** GOVERNS (never overrides a deterministic link) and is idempotent
  on re-run. The matcher is injectable (`ScriptedMatcher` for tests,
  `ClaudeGovernsMatcher` over Bedrock/Anthropic via `enrich.provider`). Off by
  default — `ckg enrich --decisions` (or `CodeGraph.infer_governs`); USD-capped by
  `knowledge.infer_budget_usd`.

- **Embed ADR/doc prose for semantic search (feat-010).** The embed pass now embeds
  `DocChunk` prose (ADR sections) into the vector store, tagged `source_type: doc`
  (code chunks tagged `source_type: code`). A doc-chunk vector hit surfaces the
  chunk **and** seeds its containing `Decision`, which expands through `GOVERNS` to
  the code it governs — so an architectural query ("why is auth built this way?")
  reaches the decision and the governed code, not just prose. Clean-replaced by the
  `DocChunk` kind each embed run (GCs vectors for removed ADRs); `EmbedReport.
  doc_chunks` counts them. (Doc-incremental-by-hash and `source_type`-aware
  code-vs-doc retrieval weighting are follow-ups.)

_Work toward 0.3.0 (`0.3.0.dev0`). Open backlog: small BUG-006 resolver residuals
(ESM named-import aliases `import { a as b }` bind the original name; ESM
`export { x }` / re-export chains; C++ implicit-`this` bare calls) and the ENH-009
cross-encoder measurement campaign (on hold — needs the `rerank` extra + creds,
not runnable in CI). A fix-only 0.2.1 can still be cut off a branch if a small
fix lands first._

## [0.2.0] - 2026-06-18

A feature minor: the **temporal / git-evolution layer** (feat-009), a
**cross-encoder reranker** seam (ENH-009), and a deep **resolver-completeness
sweep** that brings intra-type method-call resolution to **all 10 language packs**
(BUG-006 #62–#72). Validated with a full pre-release pass (test suite, real-repo
resolver sweeps, temporal end-to-end, incremental==full, MCP-over-the-wire, a
Neo4j + pgvector server-backend e2e, and an agent dogfood over the 10 tools) —
no product bugs found. The on-disk index schema is unchanged from 0.1.0; the
temporal sidecar (`.ckg/temporal.db`) is opt-in and additive.

### Added (0.2.0)

- **C++ inline method modeling + `this->f()` resolution (BUG-006 residual).** The
  cpp pack now extracts inline struct/class method *definitions* (`double area()
  const { … }`) as `Method` symbols, and the reference query captures member/arrow
  call receivers (`this->f()` / `obj.f()` / `ptr->f()`). So `this->f()` binds to a
  method of the enclosing class — **intra-type method calls now resolve across all
  10 language packs** (C++ was the last with the gap). Any other receiver stays
  unresolved (ADR-0004); a bare implicit-`this` call (`area()` with no receiver)
  is left unresolved to avoid mis-binding to a same-named free function.

- **Aliased / submodule import resolution (Python, BUG-006 residual).** An aliased
  whole-module import (`import pkg.mathutils as mu`) now captures the alias as the
  module's local binding name, and a submodule named-import (`from pkg import
  mathutils`, where `mathutils` is a *module*, not a def of `pkg`) aliases the
  local name to that submodule and points the `IMPORTS` edge at the submodule
  file. Both feed the module-alias map, so `mu.f()` / `mathutils.f()` and
  qualified bases through them resolve. An aliased import of an *external* module
  stays unresolved (never guessed onto a same-named local, ADR-0004).

- **Qualified base resolution (Python / JS / TS, BUG-006 residual).** A qualified
  superclass — `class B extends mod.Base` / `class B(mod.Base)` — now resolves to
  the base class by splitting the receiver and binding it via the importing
  **module alias** (`import mod`, `const mod = require(...)`, `import * as mod from
  …`). This emits the `INHERITS` edge and lets inherited `self.f()`/`this.f()`
  calls resolve through it, where previously a member-expression base was not
  captured at all. ESM namespace imports (`import * as ns from "./m"`) are now
  captured for JS/TS as part of this (they previously produced no IMPORTS edge or
  alias). A qualified base whose receiver is not an imported module stays
  unresolved (never guessed, ADR-0004).

- **Export-member modeling (JavaScript, BUG-006 residual).** Assigned-property
  CommonJS exports whose value is an *anonymous* function are now extracted as
  `Function` symbols: `exports.foo = function(){}` / `= () => {}`,
  `module.exports.foo = …`, and inline-function values in a `module.exports = {
  foo: () => {} }` object literal. The property name is the export name. These
  previously had no symbol to bind to, so `m.foo()`, `const { foo } =
  require(...)`, and direct calls all went unresolved; they now resolve. Non-
  function assignments (`exports.x = someVar`, a re-export of an existing binding)
  do not mint a spurious symbol (ADR-0004). Shorthand object exports (`{ a, b }`
  naming top-level defs) already resolved and are unchanged.

- **Go receiver-method call resolution (BUG-006 residual).** Go's method receiver
  is a named variable (`func (s *Server) …`), not a `self`/`this` keyword, so the
  extractor now records each method's receiver var + type and the resolver indexes
  methods by `(package, type)`. A call on the method's own receiver (`s.f()`) binds
  to a method of that **type** — more precise than the prior bare-name match,
  which could hit another type's same-named method. With this, intra-type method
  calls resolve across all 9 of the 10 packs (C++ pending method modeling).

- **Inherited-method call resolution (Python).** A `self.f()` whose method is
  defined on a base class now resolves by walking the `INHERITS` superclass map —
  binding to the base method when exactly one base defines it (an own-class
  override wins; ambiguous multi-base definers stay unresolved, no MRO guessing).
  Recovers inherited-call edges for the template-method / base-helper patterns.
- **`INHERITS` edges + inherited-method calls (8 languages).** Class inheritance
  is now extracted and resolved — a class's base classes are bound to in-repo
  class nodes, emitting `INHERITS` edges (subclass → base) for same-file and
  imported bases, and `self.f()`/`this.f()` calls to a base method resolve via
  the superclass map. Covers **Python, TypeScript, JavaScript, Java, C#, Ruby,
  and PHP** (each pack captures its own `extends`/`<`/`:` superclass). The edge
  kind was in the locked vocab but never produced — repo-map centrality ranking
  and retrieval expansion already reference it, so this fills a real gap.
  External / by-name-only bases stay unresolved (never guessed, ADR-0004);
  implemented interfaces (a separate relation), qualified bases, and Rust/Go/C++
  (different inheritance models) are follow-ups.

- **Intra-class call resolution (BUG-006 residual).** The reference queries now
  capture the call *receiver*, so the resolver binds `self.f()` / `this.f()` /
  `$this->f()` to a method **of the enclosing class** — recovering the
  intra-class call graph (CALLS edges for impact/neighbors that were previously
  missing) across **Python, TypeScript, JavaScript, Java, C#, Rust, Ruby, and
  PHP**. It also stops a latent mis-bind: a member call on any other receiver
  (`obj.f()`) is left unresolved instead of being guessed onto a same-named
  module-level function (ADR-0004). Go (named-variable receiver), C++ (methods
  not yet modeled), and inherited-method calls remain follow-ups.
- **Module-member call resolution (BUG-006 residual).** `m.f()` where `m` is an
  imported module — a whole-module import (`import m`) or a default require
  (`const m = require("./m")`) — now binds to module `m`'s top-level export `f`,
  via a receiver→module alias map in the resolver. A non-module receiver is still
  never guessed (ADR-0004). Members that aren't top-level defs (object-literal /
  assigned-property exports) still need export-member modeling.
- **Cross-encoder reranker (ENH-009).** `retrieve.rerank: cross_encoder` adds a
  real semantic re-score of the top-k candidates via a `sentence-transformers`
  cross-encoder (the `rerank` extra; `rerank_model` to override), blended with
  the base score. The model is lazy-loaded behind a `CrossScorer` seam so the
  base install and CI stay torch-free. Also **fixes** the MCP engine, which
  built its retriever without a reranker — so `retrieve.rerank` (lexical or
  cross-encoder) was silently ignored over MCP and now applies on both the CLI
  and agent-tool paths. Opt-in; default stays `off` pending a measurement
  campaign.
- **Temporal layer — `as_of` + retention (feat-009, chunk 5, completes feat-009).**
  `CodeGraph.retrieve(as_of=<commit>)` and `ckg query --as-of <commit>`
  reconstruct results as they were at a commit: `TemporalIndex.alive_at(C)`
  replays the log over the current node set (a symbol is alive iff its last
  lifecycle event at/before `C` is `OPENED`), and the Retriever drops code
  symbols added after `C`. A commit older than the `retention_commits` horizon
  raises `TemporalError` rather than answering wrong. Retention pruning of old
  `CLOSED` events runs at the end of each index/refresh. Verified by a
  per-commit equivalence property: `alive_at(C)` equals the symbol set a full
  index at `C` produces, for every backfilled commit.
- **Temporal layer — history backfill (feat-009, chunk 4).** `ckg index
  --history N` (or `--history full`) seeds the evolution log for code that
  predates temporal adoption: it replays the last N commits oldest→newest
  through the incremental pipeline against a **throwaway** store (file content
  read from git via `git ls-tree`/`git show` — no checkout, the HEAD index and
  embeddings are untouched), recording each symbol's `OPENED`/`CLOSED`. A
  symbol's earliest `OPENED` then becomes its **true introduction commit**, so
  `history().introduced` is no longer window-bounded for pre-existing code, and
  symbols deleted before HEAD get their lifecycle recorded (for `as_of`).
  Resumable via a `backfilled_through` cursor (surfaced in `ckg status`); churn
  mining is skipped during replay (a HEAD-time signal).
- **Temporal layer — read APIs (feat-009, chunk 3).** A `TemporalIndex`
  (`history` / `changed_since` / `authors` / `churn`) reads the sidecar to answer
  the questions an agent asks after a regression. New CLI: `ckg history <symbol>`
  (introduced / last-changed / churn / authors / lifecycle events) and
  `ckg changed-since <ref> [--scope GLOB]` (symbols changed since a ref, newest
  first); `ckg status` gains a `temporal:` line. New MCP tool **`ckg_history`**.
  `introduced` prefers the exact chunk-1 `OPENED` event over the window-bounded
  mined estimate. Read-only; still opt-in.
- **Temporal layer — churn / authorship (feat-009, chunk 2).** When `temporal`
  is enabled, a refresh now mines `git log` over a bounded window and attributes
  each diff hunk to the symbol whose span it overlaps, storing bounded
  per-symbol aggregates (`churn_30d/90d`, `top_authors`, `introduced`,
  `last_changed`) in the `.ckg/temporal.db` sidecar and **denormalising** them
  onto each symbol's node `attrs`. `ckg_symbol` / retrieval surface these on the
  item (`temporal: {…}`) for free. New `GraphStore.set_attrs` — a partial-attrs
  merge that preserves file ownership (Kuzu + Neo4j). Still opt-in and off by
  default; chunk 1 (sidecar + lifecycle) shipped earlier in this cycle.

## [0.1.0] — 2026-06-16

First production-grade release: a deterministic **Code Knowledge Graph** engine
plus an agent tool surface, built on the AgentForge framework. The whole pipeline
— `index → embed → enrich → query / map / decisions / routes / explain` — works
end-to-end on real code across ten languages, and a real agent answers real
questions over the tools, unattended.

### Languages (10 packs, each validated on a real OSS repo)

- **Python**, **TypeScript**, **JavaScript**, **Go**, **Ruby**, **PHP**,
  **Java**, **C#**, **Rust**, and **C++** (Tier B). Each pack extracts the
  language's real symbol surface and resolves imports per its actual model:
  file-level (Py/TS/JS), directory-package + `go.mod` (Go), `require_relative`
  wildcard (Ruby), namespace/FQN (PHP/Java), namespace-prefix (C#), path-derived
  modules (Rust), and relative `#include` (C++). Validated on click, zod,
  express/chalk, cobra, thor, monolog, gson, Newtonsoft.Json, fmt, serde_json.

### Engine

- **Two-pass ingestion** (feat-002): file-isolated tree-sitter extraction →
  graph-only import/call resolution. Conservative — an edge is created only on a
  unique match; ambiguous/external refs are tallied, never guessed (ADR-0004).
- **Incremental indexing** (feat-004): content-hash change detection + scoped
  re-extract/re-resolve; `ckg index` is incremental by default (`--full` to force).
  Correctness held by a `refresh == full` equivalence property test.
- **Storage** (feat-003, ENH-004): embedded **Kuzu** (graph) + **LanceDB**
  (vectors) by default; opt-in **Neo4j** and **pgvector** server backends behind
  the driver registry, each passing the same conformance suite (verified in CI
  against live containers).
- **AST chunking + embeddings** (feat-005): Cohere embed-v4 on Bedrock, OpenAI /
  local OpenAI-compatible, or a deterministic fake for CI.
- **Budget-aware repo map** (feat-007): dependency-free personalized PageRank, with
  a public-API orientation bias (ENH-007).
- **Hybrid retrieval** (feat-006): vector entry → typed graph expansion →
  provenance-weighted merge. Optional opt-in lexical reranker (ENH-009).

### Differentiators

- **ADR / decision ingestion** (feat-010): `Decision` nodes with parsed
  `GOVERNS`/`SUPERSEDES`, surfaced in retrieval and via `ckg decisions`.
- **Framework-aware extraction** (feat-011): FastAPI routes → `Route` +
  `HANDLED_BY`, riding the incremental FileSubgraph.
- **LLM enrichment** (feat-012): design-pattern tags + bottom-up summaries via a
  budgeted, resumable, idempotent judge (Claude on Bedrock / Anthropic API),
  pluggable provider registry (ENH-003).

### Serving / consumption

- **MCP server** (feat-008): nine read-only tools (`ckg_search`, `ckg_repo_map`,
  `ckg_symbol`, `ckg_impact`, `ckg_neighbors`, `ckg_status`, `ckg_routes`,
  `ckg_decisions`, `ckg_explain`) over **stdio** and **streamable-HTTP**; the same
  `Tool` instances back `code_graph_tools()` for in-process agents.
- **HTTP auth** (ENH-005): optional bearer-token gate (`401` on mismatch, never
  logged) + bind-safety (a non-loopback bind without a token is refused).
- **`ckg` CLI**: `index`, `status`, `embed`, `query`, `map`, `routes`,
  `decisions`, `enrich`, `summaries`, `tagged`, `serve-mcp` — uniform repo-path
  argument (ENH-006).

### Validation

- Every language pack validated on ≥1 real OSS repo, with a creds-enabled
  (embed + retrieval + enrich) run; bugs found-and-fixed along the way
  (BUG-001…008). A real `Agent` answered questions over the tools unattended,
  on both Python and Go repos (W4 + cross-language dogfood). See `docs/validation/`.
- **Pre-release validation pass** on real repositories: incremental indexing is
  byte-identical to a full re-index on real churn (`pallets/click`, modulo
  provenance — fixed BUG-007, an overload-resolution non-determinism); the MCP
  transports drive a real client over stdio + authed HTTP end-to-end; the
  Neo4j + pgvector server path holds through `index → embed → enrich → query`
  on a real repo (fixed BUG-008, a default-config `ckg query` break); and parse
  coverage holds at scale (`django`, 2922 files, ~100%, no crash).

[Unreleased]: https://github.com/Scaffoldic/agentforge-graph/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/Scaffoldic/agentforge-graph/compare/v0.3.3...v0.4.0
[0.3.3]: https://github.com/Scaffoldic/agentforge-graph/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/Scaffoldic/agentforge-graph/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/Scaffoldic/agentforge-graph/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Scaffoldic/agentforge-graph/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Scaffoldic/agentforge-graph/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Scaffoldic/agentforge-graph/releases/tag/v0.1.0
