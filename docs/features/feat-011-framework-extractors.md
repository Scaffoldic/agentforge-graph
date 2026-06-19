# feat-011: Framework-aware extractors

## Metadata

| Field | Value |
|---|---|
| **ID** | feat-011 |
| **Title** | Framework-aware extractors (routes, ORM, DI as graph edges) |
| **Status** | proposed |
| **Owner** | kjoshi |
| **Created** | 2026-06-11 |
| **Target version** | 0.4.0 |
| **Languages** | python |
| **Module package(s)** | `agentforge_graph.frameworks` (+ per-framework packs) |
| **Depends on** | feat-002 |
| **Blocks** | none |

---

## 1. Why this feature

Differentiator #2. A web app's real architecture is invisible in a
plain symbol graph: `POST /payments` → handler → service →
`Payment` model is connected through decorators, DI containers, and
ORM metaclasses — not through plain calls. The survey found exactly
one tool that models frameworks (CodeQL: Spring, Django, Express,
Rails… — unverified detail, research §2.2), and it keeps that
knowledge locked inside query libraries for security analysis. **No
tool exports framework semantics as graph edges an agent can
traverse.** Yet "find the handler for this endpoint" and "what
tables does this feature touch" are top-frequency agent questions.

## 2. Why it must ship in the agent core

- Framework packs are tree-sitter query packs + post-processing over
  feat-002's parse trees and subgraphs — they only stay cheap and
  consistent by riding the existing extraction pipeline (same
  file-isolation, same incremental hooks, same provenance).
- Edge vocabulary (`HANDLED_BY`, `INJECTED_INTO`, `HAS_FIELD`,
  `RELATES_TO`) is locked schema (feat-001); per-agent invention
  would fragment it — the precise drift CodeQL avoided with curated
  per-framework models.
- CodeQL's lesson (research §2.2): framework knowledge is **curated
  rule packs, not inference**. Curation needs one home.

## 3. How consumers benefit

- `ckg_routes` lists every endpoint with method, path pattern, and
  handler symbol — the agent's API surface map in one call, no
  decorator-grepping.
- Retrieval for "payment retry logic" expands through `HANDLED_BY` /
  `RELATES_TO` to return the route, handler, service, *and* the ORM
  models with their relations — the vertical slice agents actually
  need to make a safe change.
- "What writes to the `users` table" becomes a graph query
  (`DataModel ←HAS_FIELD/RELATES_TO` + reverse references) instead
  of a hope.

## 4. Feature specifications

### 4.1 User-facing experience

```bash
ckg index            # framework packs auto-activate on dependency detection
ckg routes           # table: METHOD PATH → handler symbol (file:line)
ckg models           # DataModel nodes + relations
```

```python
routes = await graph.routes()
slice_ = await graph.retrieve("how is a payment refunded")  # crosses framework edges
```

### 4.2 Public API / contract

**New node kinds** (reserved in feat-001): `Route` (attrs: `method`,
`path_pattern`, `framework`), `DataModel` (attrs: `table?`,
`framework`), `Service` (DI-registered component).

**Edges:**

| Edge | Meaning |
|---|---|
| `HANDLED_BY` Route→Function | endpoint dispatch |
| `HAS_FIELD` DataModel→Variable | column/field with type attrs |
| `RELATES_TO` DataModel→DataModel | FK / has-many / many-to-many (`attrs.kind`) |
| `INJECTED_INTO` Service→Class/Function | DI provision site |

```python
class FrameworkPack(ABC):
    name: str                       # "fastapi"
    @abstractmethod
    def detect(self, repo: RepoSource) -> bool      # dep manifests, imports
    @abstractmethod
    def extract(self, file: SourceFile,
                subgraph: FileSubgraph) -> FrameworkFacts
    def resolve(self, store: GraphStore) -> list[Edge]:  # optional pass 2
        ...
```

**Pack roadmap:** 0.4: FastAPI, Django (routes + ORM), SQLAlchemy.
0.5: Flask, Express/NestJS (TS), Spring (Java, with the Java
language pack). Community packs via entry point
`agentforge_graph.framework_packs`.

### 4.3 Internal mechanics

- **Detection:** packs activate per repo via manifest/deps scan
  (`pyproject`, `package.json`) + import confirmation — never run N
  packs against every file.
- **Extraction (pass 1, file-isolated):** decorator patterns
  (`@app.get("/x")`), class-pattern matches (Django `Model`
  subclasses, SQLAlchemy declarative), DI registration sites. Emits
  framework nodes/edges with `source="parsed"`,
  `extractor="pack:fastapi@<ver>"`.
- **Resolution (pass 2):** stitches indirections — FastAPI routers
  included with prefixes (`include_router(r, prefix="/api")` →
  final `path_pattern`), Django `urls.py` string references to
  views, SQLAlchemy `relationship("User")` string targets — using
  the graph built in pass 1. Mirrors feat-002's two-pass design and
  inherits feat-004 incrementality unchanged (packs declare which
  files are resolution-coupled, e.g. `urls.py`).
- Pattern coverage is **versioned per pack** and golden-tested
  against real-world fixture apps; unrecognized dynamic registration
  (routes built in loops, etc.) is counted and reported in
  IndexReport — no silent gaps.

### 4.4 Module packaging

`agentforge_graph.frameworks` core + built-in packs in-tree;
third-party packs as pip packages.

### 4.5 Configuration

```yaml
frameworks:
  enabled: auto          # auto-detect | explicit list | off
  packs: []              # force-enable, e.g. ["fastapi"]
```

## 6. Cross-language parity

Packs are language-pack-dependent. Because all 10 v0.1 language packs
(incl. Java, Go, C#, Ruby, PHP) land in feat-002, framework packs are
unblocked across the whole stack at 0.4 — Spring (Java), Rails (Ruby),
Laravel (PHP), Gin (Go), and ASP.NET (C#) become feasible without
waiting on language support. Tier B (C++) frameworks are deferred
until C++ resolution matures.

## 7. Test strategy

- Golden fixtures: one small-but-real app per framework (FastAPI
  with routers+deps, Django with apps+FKs, SQLAlchemy with
  relationship strings) → expected Route/DataModel/edge sets.
- Resolution: prefix composition, string-target resolution,
  cross-file include chains.
- Negative: repo without the framework → pack inactive, zero nodes.
- Incremental: edit one router file → only coupled files re-resolve
  (extends feat-004 equivalence property to framework facts).

## 8. Risks & open questions

| Risk / Question | Mitigation / Decision |
|---|---|
| Pattern coverage is a treadmill (frameworks evolve) | Versioned packs, golden fixtures pinned to framework versions, coverage gaps reported not hidden; CodeQL sustains this model — it's labor, not risk |
| Dynamic/metaprogrammed registration unparseable statically | Count + report unrecognized registrations; optional LLM assist per gap is a feat-012-style enricher, post-0.4 |
| Edge taxonomy too web-centric (what about CLIs, queues, cron?) | `Route` generalizes to entry points (`attrs.protocol: http\|cli\|queue\|schedule`); taxonomy review before locking at 0.4 |
| Pack quality bar for community packs | Conformance suite + fixture-app requirement for listing |

## 9. Out of scope

- Security/taint semantics (CodeQL's actual job) — we model
  topology, not data flow.
- Runtime verification of routes (no app boot, static only).
- Infra-as-code edges (Terraform, K8s) — interesting, separate
  feature if demanded.

## 10. References

- Research §2.2 (CodeQL framework models — unverified), §3.3
  (framework-edge gap), §5 item 12.
- feat-001 (edge kinds), feat-002 (pipeline ridden), feat-004
  (incremental contract), feat-008 (`ckg_routes` reserved).

---

## Implementation status

**MVP shipped** (branch `feat/011-framework-extractors`) — **FastAPI routes**.
New package `agentforge_graph.frameworks` (zero `agentforge` imports):
`FrameworkPack` ABC + `FrameworkFacts`, `FrameworkRegistry`, dependency/import
detection (`active_frameworks`), `FrameworkExtractor`, and the built-in
**FastAPI** pack (`routes.scm` → `Route` nodes + `HANDLED_BY` edges to the
handler `Function`).

Framework facts **ride the file's `FileSubgraph`** (pass-1 merge), so they
inherit feat-004 incrementality unchanged — a changed file re-emits its routes,
`clear_resolved` never touches them (they're `parsed`/file-owned). Surfaces:
`CodeGraph.routes()`, `ckg routes` CLI, the `ckg_routes` MCP tool (now in
`ALL_TOOLS`), and a `frameworks:` config block (`enabled: auto|off|<list>`,
`packs`). `IndexReport` gains `routes_extracted` + `framework_unresolved`
(dynamic paths and class-based handlers counted, never silently dropped).

≥97% package coverage; `mypy --strict` + ruff clean. Design:
`docs/design/design-011-framework-extractors.md`.

**ORM models shipped (0.4 follow-on)** — **SQLAlchemy declarative models**.
The built-in **SQLAlchemy** pack (`models.scm` + body analysis) emits a
`DataModel` node per declarative model (table from `__tablename__`, the
underlying class symbol in `attrs.class`) with `HAS_FIELD` edges to each mapped
column — a `Variable` field carrying its `column_type`. Both classic
(`name = Column(Integer)`) and 2.0-style (`id: Mapped[int] = mapped_column()`)
forms are recognised; a class mints a model only with declarative evidence
(`__tablename__` or ≥1 column), so plain classes never become false models
(ADR-0004). Surfaces: `CodeGraph.models()`, `ckg models` CLI, `IndexReport.
models_extracted`.

**ORM `RELATES_TO` shipped (0.4 follow-on)** — the framework **pass-2** hook
(`FrameworkPack.resolve` / `FrameworkExtractor.resolve`) is now wired into both
the full pipeline and the incremental indexer. Pass-1 records each
`relationship("X")` / `ForeignKey("t.c")` string target on the model node;
pass-2 stitches them into `RELATES_TO` edges (`attrs.kind` = `relationship`|`fk`,
`attrs.via` = the field) — `relationship` to the model whose class is `X`, `fk`
to the model whose table matches. Unique-match-only (ambiguous class names left
unresolved, ADR-0004). Globally idempotent (clear all `RELATES_TO` + rebuild
from the whole-repo model set), so an incremental refresh converges to the
full-index graph. Surfaced in `ModelInfo.relations`, `ckg models`, and
`IndexReport.relations_resolved`.

**Django models shipped (0.4 follow-on)** — the built-in **Django** pack mirrors
the SQLAlchemy one over the shared ORM rails (`frameworks/orm.py` pass-2 +
`packs/_python_ast.py` helpers). A class is a `DataModel` when it has a `Model`-
tail base (`class X(models.Model)`) or any `models.*Field` assignment (catching
abstract-base subclasses); fields are the `*Field(...)` columns (table from
`class Meta: db_table` when set). `ForeignKey`/`OneToOneField`/`ManyToManyField`
targets (class ref, `"app.Model"` string, or `"self"`) become `RELATES_TO`
edges (`attrs.kind` = `fk`|`o2o`|`m2m`) — FK/O2O also a `HAS_FIELD` column, M2M
relation-only. Resolves by class name against the whole-repo model set.

**DI shipped (0.4 follow-on)** — the FastAPI pack now models dependency
injection. A parameter defaulting to `Depends(provider)` / `Security(provider)`
becomes a `Service` node (the provider) + an `INJECTED_INTO` edge to the
consuming function — so "what is injected into this handler" / "where is
`get_db` used" are graph queries. Surfaced via `CodeGraph.services()`, `ckg
services`, and `IndexReport.services_extracted`. Grounding the provider name to
its definition (cross-file) is a follow-up.

**Class-based handlers/consumers shipped (0.4 follow-on)** — a route decorator
or `Depends`/`Security` parameter on a *method* now resolves to its
`Class#method` symbol (verified: `HANDLED_BY`/`INJECTED_INTO` land on the real
method node) instead of being counted unresolved. Only a dynamic (non-literal)
route path remains unresolved.

### Follow-ups (same harness)
- Cross-file pass-2: `include_router(prefix=…)` composition, Django `urls.py`
  string view refs (the `resolve()`/`coupled_files()` hooks are reserved).
- Flask, Express/NestJS (TS), Spring (Java).
- Ground DI provider names to their function definitions (cross-file).
