# Design Doc: feat-011 framework-aware extractors (FastAPI routes first)

> Per-feature design doc (design stage). Mirrors
> `docs/features/feat-011-framework-extractors.md`. The spec says *what & why*;
> this doc says *how*, and **scopes the first PR** to a coherent MVP.

---

## Metadata

| Field | Value |
|---|---|
| **Title** | feat-011 framework-aware extractors — FastAPI routes (MVP) |
| **Status** | accepted |
| **Owner** | kjoshi |
| **Created** | 2026-06-13 |
| **Last updated** | 2026-06-13 |
| **Related features** | feat-011 (this) · rides feat-002 pipeline · inherits feat-004 incrementality · fills feat-008's reserved `ckg_routes` |
| **Related ADRs** | ADR-0001 (layering), ADR-0004 (provenance), ADR-0005 (locked kinds) |

---

## 1. Context

Differentiator #2: a web app's real architecture — `POST /payments` → handler →
service → `Payment` model — is invisible in a plain symbol graph because it's
wired through decorators, DI, and ORM metaclasses, not calls. No tool *exports*
framework semantics as traversable graph edges. The kinds are already locked
(feat-001): `Route`/`DataModel`/`Service` nodes, `HANDLED_BY`/`HAS_FIELD`/
`RELATES_TO`/`INJECTED_INTO` edges; feat-008 reserved the `ckg_routes` tool.

**Why FastAPI-routes-first.** The spec's 0.4 target is FastAPI + Django + SQLAlchemy
across routes/ORM/DI — too much for one PR. FastAPI routes are the cleanest,
highest-value slice: decorator-based, **intra-file** (decorator and handler in
the same file), trivially golden-tested, and they light up `ckg routes` /
`ckg_routes` — the "API surface in one call" agents ask for constantly. ORM
(`DataModel`/`HAS_FIELD`/`RELATES_TO`), DI (`Service`), Django, and cross-file
router-prefix composition become follow-up packs/passes over the **same
harness** — exactly how the language packs (TS, JS) followed feat-002.

## 2. Goals

- `agentforge_graph.frameworks` — a new engine package, **zero `agentforge`
  imports** (ADR-0001). A `FrameworkPack` ABC + registry + detection, and one
  built-in **FastAPI** pack.
- Framework facts **ride the file's `FileSubgraph`** (pass-1, file-isolated):
  emitted with the language nodes/edges, upserted under the file's
  `origin_path`, so feat-004 incrementality applies *for free* — a changed file
  re-emits its routes, a deleted file drops them, no resolver change.
- `Route` nodes (`method`, `path`, `framework` attrs) + `HANDLED_BY`
  Route→Function edges, `source="parsed"`, `extractor="pack:fastapi@<fp>"`.
- Detection: activate a pack per repo via dependency-manifest scan + import
  confirmation — never run packs against a repo that doesn't use the framework.
- Surfaces: `CodeGraph.routes()`, `ckg routes` CLI, `ckg_routes` MCP tool
  (added to `ALL_TOOLS`). `frameworks:` config block.
- Unrecognized/dynamic registrations are **counted and reported** in
  `IndexReport`, never silently dropped.
- ≥90% coverage; `mypy --strict`; ruff.

## 3. Non-goals (explicit follow-ups)

- **ORM** (`DataModel`/`HAS_FIELD`/`RELATES_TO`) and **DI** (`Service`/
  `INJECTED_INTO`) — next packs/passes; the ABC already has room for them.
- **Cross-file pass-2 resolution** — `include_router(r, prefix="/api")` prefix
  composition and string-target view refs (Django `urls.py`). The MVP extracts
  routes at their definition site without prefix composition; the `resolve()`
  hook is defined but a no-op for FastAPI MVP (a counted limitation, §7).
- **Django, Flask, Express/NestJS, Spring** — later packs (Express/NestJS need
  the TS pack's framework variant).
- Methods-as-handlers inside classes (class-based views) — MVP handles
  top-level `def` handlers (the dominant FastAPI shape); class methods counted
  as unresolved for now.
- Security/taint (curated rule-pack analyzers' job); runtime route verification.

## 4. Proposal

### 4.1 Package layout

```
src/agentforge_graph/frameworks/
  __init__.py        # FrameworkPack, FrameworkFacts, FrameworkRegistry, builtin_framework_registry
  base.py            # FrameworkPack ABC + FrameworkFacts
  registry.py        # FrameworkRegistry + builtin registry
  detect.py          # active_frameworks(repo_path, config) -> list[FrameworkPack]
  extractor.py       # FrameworkExtractor — runs active packs over one file
  packs/
    fastapi/
      __init__.py    # FASTAPI_PACK
      routes.scm     # tree-sitter query: decorated route functions
src/agentforge_graph/
  config.py              # + FrameworksConfig
  ingest/pipeline.py     # thread active packs → merge framework facts into each FileSubgraph
  ingest/codegraph.py    # detect frameworks; pass to pipeline/indexer; + routes()
  ingest/report.py       # IndexReport + routes_extracted / framework_unresolved
  serve/tools.py         # + CkgRoutes, in ALL_TOOLS
  serve/engine.py        # + routes() passthrough
  cli.py                 # + `ckg routes`
tests/frameworks/        # fixtures/fastapi app + golden assertions + conformance
```

### 4.2 The `FrameworkPack` ABC (`base.py`)

```python
class FrameworkFacts(BaseModel):
    nodes: list[Node] = []
    edges: list[Edge] = []
    unresolved: int = 0          # dynamic/unparseable registrations seen, counted

class FrameworkPack(ABC):
    name: str                    # "fastapi"
    language: str                # "python" — only runs on that pack's files
    version: str                 # fingerprint for IndexReport / future --full

    @abstractmethod
    def detect(self, repo_path: Path, source_texts: Iterable[str]) -> bool:
        """Active for this repo? Dependency manifest + import confirmation."""

    @abstractmethod
    def extract(self, file: SourceFile, lang: Any, repo: str, commit: str) -> FrameworkFacts:
        """Pass-1, file-isolated: emit Route/DataModel/... nodes + edges to
        the symbols the language extractor produced (same SymbolID scheme)."""

    def resolve(self, store: GraphStore) -> list[Edge]:
        """Optional pass-2 (cross-file stitching). MVP: returns []."""
        return []

    def coupled_files(self, path: str) -> bool:
        """Files whose change forces a framework re-resolve (e.g. urls.py).
        MVP: False (no pass-2)."""
        return False
```

`extract` is handed the parsed `tree_sitter.Language` (so the pack builds its
own `Query`/`QueryCursor` over a fresh parse of the file — file-isolated,
decoupled from the language extractor; one extra parse per active-framework
Python file, acceptable, noted as a future tree-reuse optimization).

### 4.3 The FastAPI pack (`packs/fastapi/`)

`routes.scm` (Python grammar) captures a decorated route function:

```scheme
(decorated_definition
  (decorator
    (call
      function: (attribute object: (identifier) @app attribute: (identifier) @method)
      arguments: (argument_list (string) @path)))
  definition: (function_definition name: (identifier) @handler)) @route
```

`extract` keeps a capture only when `@method ∈ {get,post,put,delete,patch,
options,head}` and `@app` is an app/router identifier (any name; FastAPI
convention is `app`/`router`). For each kept match:

- **handler symbol id** = `SymbolID.for_symbol("py", repo, path,
  Descriptor.method(handler_name))` — matches the top-level `Function` node the
  Python extractor emitted (so `HANDLED_BY` lands on a real node, same file →
  both endpoints present in one `FileSubgraph`, edge MATCH succeeds).
- **route id** = `SymbolID.for_symbol("py", repo, path,
  f"route({METHOD} {path}).")`. The space in the descriptor is escaped by
  `for_symbol` and round-trips through `parse` (verified) — so the id is one
  valid 5-field symbol. `Route` node carries
  `attrs={method, path, framework:"fastapi"}`, `span` = the decorator line,
  `provenance = Provenance.parsed("pack:fastapi@<fp>", commit)`.
- **edge** `Route -HANDLED_BY-> handler`, same provenance.

A decorator whose target is a class method or whose path/method can't be read
statically increments `FrameworkFacts.unresolved` (counted, surfaced).

`detect`: repo has `fastapi` in `pyproject.toml`/`requirements*.txt` **or** any
indexed Python file contains `import fastapi` / `from fastapi`.

### 4.4 Pipeline integration — facts ride the FileSubgraph

`FrameworkExtractor(packs)` runs the active packs over a `SourceFile` and
returns merged `FrameworkFacts`. In `IngestPipeline._extract_one`, after the
language `FileSubgraph` is built, run the framework extractor for that file's
language and **append** its nodes/edges to the subgraph before `upsert`:

```python
sg = TreeSitterExtractor(pack, repo, commit).extract(sf)
facts = framework_extractor.extract_for(sf, pack)   # active packs for sf.language
sg = sg.model_copy(update={"nodes": sg.nodes + facts.nodes,
                           "edges": sg.edges + facts.edges})
```

Because the merged nodes/edges are upserted under the file's `origin_path`,
**feat-004 handles incrementality with no change**: edit the file → re-extract
→ routes re-emitted; delete the file → routes dropped; `clear_resolved`
untouched (framework edges are `parsed`, file-owned, not `resolved`). The
pipeline threads `packs` through `run(...)`; `IncrementalIndexer` passes them to
its `IngestPipeline` call too. `paths=None` (full) and scoped (incremental)
paths both merge facts identically — so the feat-004 equivalence property
extends to framework facts automatically.

`IngestPipeline` tallies `report.routes_extracted` (Route nodes) and
`report.framework_unresolved` (sum of `unresolved`).

### 4.5 Detection & wiring (`detect.py`, `CodeGraph`)

`active_frameworks(repo_path, config, registry, source) -> list[FrameworkPack]`:
honour `frameworks.enabled` (`auto` → run each pack's `detect`; an explicit
list → those packs; `off` → none) plus `frameworks.packs` force-enable. Run
once in `CodeGraph.index`/`refresh`, pass the result into the pipeline/indexer.

`CodeGraph.routes() -> list[RouteInfo]`: query `NodeKind.ROUTE` nodes, read
`attrs` + the `HANDLED_BY` target, return `[{method, path, handler_symbol,
file, line, framework}]` sorted by (path, method).

### 4.6 Config, CLI, MCP

- `FrameworksConfig` (`KEY="frameworks"`): `enabled: str|list[str] = "auto"`,
  `packs: list[str] = []`.
- `ckg routes [--path --config]` → a table `METHOD  PATH → handler (file:line)`;
  `(no routes found)` when empty.
- `CkgRoutes(_CkgTool)` (`name="ckg_routes"`, `RoutesInput{method?, path?}`):
  returns JSON `{routes:[…], indexed_commit, dirty, truncated, …}` via the
  shared `_pack_json` envelope; added to `ALL_TOOLS` so the MCP server and
  `code_graph_tools` expose it automatically. `engine.routes()` passthrough.

### 4.7 Provenance & report

Framework nodes/edges: `source="parsed"`, `extractor="pack:fastapi@<version
fingerprint>"`, `confidence=1.0`. `IndexReport` gains `routes_extracted: int`
and `framework_unresolved: int`; `_format_report` prints a `frameworks:` line
when non-zero. No silent gaps.

## 5. Alternatives considered

| Option | Why not |
|---|---|
| Framework facts as a **separate store pass** (`store.add` after resolve) | Then they're path-less and feat-004 can't invalidate them without new machinery. Merging into the `FileSubgraph` reuses the existing per-file upsert/delete — incrementality for free. |
| Reuse the language extractor's parse tree | Couples the language extractor to frameworks. MVP re-parses per active pack (one extra parse/Python-file when FastAPI is active); tree-reuse is a later optimization. |
| Make FastAPI a `LanguagePack` variant | Conflates "what's in the language" with "what a framework adds"; framework packs must compose with *any* language pack and detect per-repo. Separate ABC. |
| Pass-2 prefix composition in the MVP | Cross-file, needs the resolve pass + coupled-file tracking; deferred and *counted* so the gap is visible, not silent. |
| LLM-infer routes | Spec / curated rule-pack analyzers' lesson: framework knowledge is curated rule packs, not inference. Static queries, versioned. |

## 6. Migration / rollout

Additive: new package, new optional config block (absent → `auto`), new node
kind already reserved (no schema bump). First `ckg index` after the feature
populates routes; `ckg index --full` not required (framework facts are derived
and ride normal extraction). `routes()`/`ckg_routes` return empty on repos
without a detected framework (negative path tested).

## 7. Risks

| Risk | Mitigation |
|---|---|
| Pattern coverage treadmill (frameworks evolve) | Versioned pack (`@<fp>`), golden fixtures pinned to a FastAPI version, coverage gaps **counted** in `IndexReport` — labor, not silent risk (curated rule-pack analyzers sustain this). |
| Dynamic/metaprogrammed routes unparseable | `unresolved` counter surfaced; LLM-assist per gap is a later feat-012-style enricher. |
| `include_router` prefixes / class-based views missed at MVP | Explicitly out of scope, counted as unresolved; `resolve()` hook reserved. |
| Route id collisions (two same method+path in a file) | Descriptor includes method+path; a genuine duplicate de-dupes to one node (correct — same endpoint). |
| Extra parse per file when active | Only for the pack's language when the framework is detected in the repo; acceptable at scale, tree-reuse noted. |

## 8. Open questions (decisions for review)

1. **Scope the first PR to FastAPI routes only** (HANDLED_BY; ORM/DI/Django and
   cross-file prefix composition as follow-ups)? Proposed: **yes**.
2. **Framework facts merged into the `FileSubgraph`** (ride feat-004) vs a
   separate post-resolve pass? Proposed: **merge** — incrementality for free.
3. **Re-parse per active pack** vs thread the language extractor's tree?
   Proposed: **re-parse** at MVP (decoupled), optimize later.
4. **Detection = manifest scan + import confirmation, `enabled: auto`** default?
   Proposed: **yes**.
5. **`ckg routes` CLI + `ckg_routes` tool + `CodeGraph.routes()`** this PR?
   Proposed: **yes** (it's the visible payoff).

## 9. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-13 | First PR = FastAPI routes MVP; ORM/DI/Django/prefix-composition follow-ups | Cleanest, intra-file, highest-value slice; same "harness then packs" path as the language packs |
| 2026-06-13 | Framework facts ride the `FileSubgraph` (pass-1 merge) | Reuses per-file upsert/delete → feat-004 incrementality + equivalence apply unchanged; framework edges are `parsed`/file-owned, never touched by `clear_resolved` |
| 2026-06-13 | `FrameworkPack` ABC separate from `LanguagePack` | Frameworks compose with any language pack and detect per-repo; different lifecycle |
| 2026-06-13 | Detection = manifest deps + import confirmation, `enabled: auto` | Never run packs on repos that don't use the framework (spec §4.3) |
| 2026-06-13 | Route id = `route(METHOD path).` descriptor; facts `source=parsed`, `extractor=pack:fastapi@fp` | Stable per-endpoint id (space escapes/round-trips); provenance/version honest (ADR-0004) |
| 2026-06-13 | Unrecognized registrations counted in `IndexReport`, not dropped | No silent gaps (spec §4.3) |

## 10. Chunk plan (the single feat-011 PR)

| Chunk | Commit | Contents |
|---|---|---|
| 0 | `chore(011): FrameworksConfig + frameworks package skeleton; design accepted` | `FrameworksConfig`; `frameworks/__init__` + `base.py` (ABC + `FrameworkFacts`); this doc → accepted |
| 1 | `feat(011): FastAPI pack — route extraction (routes.scm)` | `packs/fastapi/` + `FrameworkExtractor`; unit golden tests on a fixture app (Route nodes, HANDLED_BY, unresolved counter) |
| 2 | `feat(011): detection + registry` | `detect.py` (manifest + import), `registry.py`; active/inactive (negative) tests |
| 3 | `feat(011): pipeline merge + IndexReport + incrementality` | thread packs through `IngestPipeline`/`IncrementalIndexer`; merge facts into `FileSubgraph`; report counters; incremental + equivalence-extension test |
| 4 | `feat(011): CodeGraph.routes + ckg routes CLI` | facade method + CLI table; CLI test |
| 5 | `feat(011): ckg_routes MCP tool` | `CkgRoutes` + `ALL_TOOLS` + engine passthrough; tool schema + result test |
| 6 | `test(011): layering + conformance + negative` | layering test for `frameworks`; `FrameworkPackConformance`; repo-without-framework |
| 7 | `docs(011): impl status + tracker; design accepted` | spec status; TRACKER; this doc accepted |

## 11. References

- Spec: `docs/features/feat-011-framework-extractors.md`
- ADRs: 0001 (layering), 0004 (provenance), 0005 (locked kinds)
- feat-002 (pipeline/extractor ridden), feat-004 (incremental contract —
  facts ride the `FileSubgraph`), feat-008 (`ckg_routes` reserved)
- Research §2.2 (curated rule-pack analyzers' framework models), §3.3 (framework-edge gap)
