# Design Doc: feat-002 tree-sitter ingestion pipeline

> Per-feature design doc (design stage of the pipeline). Mirrors
> `docs/features/feat-002-tree-sitter-ingestion.md`. The feature spec says
> *what & why*; this doc says *how* — concrete file layout, exact types,
> resolved decisions, test plan, chunk plan.

---

## Metadata

| Field | Value |
|---|---|
| **Title** | feat-002 tree-sitter ingestion pipeline |
| **Status** | accepted |
| **Owner** | kjoshi |
| **Created** | 2026-06-12 |
| **Last updated** | 2026-06-12 |
| **Related features** | feat-002 (this) · consumes feat-001, feat-003 · consumed by feat-004, 005, 007, 011 |
| **Related ADRs** | ADR-0001 (layering), ADR-0002 (tree-sitter over compiler), ADR-0003 (symbol IDs), ADR-0004 (provenance) |

---

## 1. Context

This is the feature that puts real data in the graph. feat-001 fixed the
schema; feat-003 gave us a place to write it. feat-002 parses a repo with
tree-sitter (zero build config — ADR-0002) and produces `FileSubgraph`s,
then resolves cross-file references in a cheap second pass.

**Scope of *this* PR.** The spec's body describes the full 10-language
vision, but its own metadata says `Languages: python`, and it states each
language pack is "an independently mergeable unit … packs can land on
separate PRs." So this PR ships the **pipeline + the Python pack (Tier A:
structure *and* import resolution) + the `ckg index` CLI**. The other nine
packs (ts, js, java, go, c#, rust, ruby, php, c++) are follow-up PRs
(`feat/002-pack-<lang>`) over the same harness — see §8. This keeps the
first PR reviewable while delivering a working `ckg index .` for Python.

## 2. Goals

- `agentforge_graph.ingest` package, **zero `agentforge` imports** (ADR-0001).
- A `TreeSitterExtractor` that passes feat-001's `ExtractorConformance`.
- A `LanguagePack` abstraction (grammar + `.scm` queries + descriptor
  rules) so adding a language is one pack, not a new pipeline.
- Two-pass design: file-isolated **extract** (parallelizable, no cross-file
  reads) → graph-only **resolve** (idempotent, edges-only).
- Honest provenance: syntactic facts are `source=parsed`; only
  import-graph-confirmed references become `source=resolved` (ADR-0004).
  Never fabricate a confident edge from a guess.
- `ckg index [PATH]` CLI writing into the feat-003 `Store`.
- ≥90% coverage; `mypy --strict`; ruff clean.

## 3. Non-goals

- The other nine language packs (follow-up PRs; harness is built for them).
- LSP-assist / Tier-B C++ resolution (post-0.1, behind config — spec §4.3).
- Incremental / watch mode (feat-004 owns change detection; this pass is
  built file-isolated *so that* feat-004 is thin).
- Data-flow, call-graph precision beyond import resolution, binary analysis.
- Chunking/embeddings (feat-005), repo map (feat-007).

## 4. Proposal

### 4.1 Package layout

```
src/agentforge_graph/ingest/
  __init__.py        # curated exports: CodeGraph, IngestPipeline,
                     #   TreeSitterExtractor, LanguagePack, IndexReport
  source.py          # RepoSource: file discovery + SourceFile construction
  pack.py            # LanguagePack, DescriptorRules; pack registry by extension
  extractor.py       # TreeSitterExtractor(Extractor) — pass 1
  resolver.py        # ImportResolver — pass 2; ResolveStats
  pipeline.py        # IngestPipeline.run -> IndexReport
  codegraph.py       # CodeGraph facade: index(...) / open(...)
  report.py          # IndexReport (counts, unresolved, skipped)
  packs/
    __init__.py      # builtin pack registry (python today)
    python/
      __init__.py    # the Python LanguagePack instance
      structure.scm  # defs/classes/imports captures
      references.scm # calls/attribute refs captures
tests/ingest/
  conftest.py
  fixtures/python/   # a tiny sample repo (committed)
  test_source.py  test_python_extractor.py  test_extractor_conformance.py
  test_resolver.py  test_pipeline.py  test_codegraph.py  test_layering.py
```

A layering test (feat-001/003 pattern) asserts nothing under `ingest/`
imports `agentforge*`.

### 4.2 Parsing — the grounded tree-sitter API

Grammars come from `tree-sitter-language-pack`, but parsing/queries use the
standalone `tree-sitter` package (the two have an ABI split — see
`docs/framework/2026-06-12-tree-sitter-language-pack-bundles-incompatible-parser.md`):

```python
from tree_sitter import Parser, Query, QueryCursor
from tree_sitter_language_pack import get_language

lang   = get_language(pack.grammar)         # tree_sitter.Language
parser = Parser(lang)                        # NOT get_parser()
root   = parser.parse(file.text.encode("utf-8")).root_node
caps   = QueryCursor(Query(lang, pack.structure_queries)).captures(root)
```

`captures()` returns `dict[capture_name, list[Node]]`; `node.start_byte/
end_byte` index the UTF-8 bytes, `node.start_point/end_point` are
`(row, col)` 0-based (we store spans 1-based per feat-001). Languages and
compiled queries are cached per pack (build once, reuse across files).

### 4.3 `RepoSource` (`source.py`)

```python
class RepoSource:
    def __init__(self, root: str | Path,
                 include: list[str] | None = None,
                 exclude: list[str] = DEFAULT_EXCLUDES,
                 max_file_kb: int = 512): ...
    def iter_files(self, registry: PackRegistry) -> Iterator[SourceFile]: ...
```

- Walks `root`; for each file, the extension picks a pack (registry maps
  `.py -> python`); files with no pack are skipped.
- Reads bytes, decodes UTF-8 (`errors="replace"`), `content_hash =
  sha256(bytes).hexdigest()`, builds a feat-001 `SourceFile`.
- Skips files over `max_file_kb` and excluded globs — **logged, never
  silent** (counted in `IndexReport.skipped`). Defaults exclude
  `node_modules`, `.venv`, `dist`, `.git`, `.ckg` (mirrors `ckg.yaml`).

### 4.4 `LanguagePack` (`pack.py`)

```python
class DescriptorRules(BaseModel):
    # capture-name -> (NodeKind, descriptor-suffix builder)
    kinds: dict[str, NodeKind]          # "def.class" -> CLASS, "def.func" -> FUNCTION, ...
    # which capture names are *containers* that nest descriptors (class, func)
    name_field: str = "name"            # field holding the identifier

class LanguagePack(BaseModel):
    language: str                        # "python" (also the SymbolID lang slug "py")
    lang_slug: str                       # short slug for symbol IDs, e.g. "py"
    grammar: str                         # tree-sitter-language-pack name
    extensions: tuple[str, ...]          # (".py",)
    structure_queries: str               # .scm text (loaded from packs/python/structure.scm)
    reference_queries: str               # .scm text
    descriptor_rules: DescriptorRules
```

Capture-name convention (shared across packs so `CALLS` means the same
everywhere): `@def.class`, `@def.function`, `@def.method`, `@name`,
`@import`, `@import.module`, `@call`, `@call.callee`, `@ref`. A pack's
`.scm` files map its grammar's node types onto these names; the extractor
is language-agnostic and keys off the capture names only.

### 4.5 `TreeSitterExtractor` (`extractor.py`) — pass 1, file-isolated

`extract(file: SourceFile) -> FileSubgraph`:

1. Parse; emit a **File** node (empty descriptor) with
   `provenance=parsed(extractor_name, commit)`.
2. Run `structure_queries`. For each definition capture:
   - `NodeKind` from `descriptor_rules.kinds[capture]`.
   - `name` = identifier text; `span` = 1-based start/end rows.
   - **descriptor** built from the chain of enclosing definition nodes
     (walk `node.parent` collecting container defs), e.g. class `Auth` +
     method `login` → `Auth#login().` via feat-001 `Descriptor` helpers.
     Overload disambiguation uses feat-001's `(+N)` rule (Nth same-name
     sibling in source order).
   - `id = SymbolID.for_symbol(lang_slug, repo, path, descriptor)`.
   - **CONTAINS** edge parent→child (parent = nearest enclosing def, else
     the File node). Intra-file only, so both endpoints always exist.
3. Run `reference_queries`. Imports and call/refs are **not** edges yet
   (their targets may live in other files — forbidden to read in pass 1).
   Record them as structured data:
   - File node `attrs["imports"] = [{"module":…, "names":[…], "line":…}]`.
   - Caller node `attrs["refs"] = [{"name":…, "line":…}]` (the enclosing
     def of each call site; module-level calls hang off the File node).

   This keeps every `Edge` endpoint a real, valid symbol id (no fabricated
   ids) and makes pass 2 the *single* place cross-file edges are created.

Determinism: same `(content_hash)` → identical `FileSubgraph` regardless of
capture order (nodes/edges sorted by `(span, id)` before return) — satisfies
`ExtractorConformance.test_extraction_is_deterministic`.

### 4.6 `ImportResolver` (`resolver.py`) — pass 2, graph-only

```python
class ResolveStats(BaseModel):
    imports_resolved: int; refs_resolved: int; refs_ambiguous: int; refs_unresolved: int

class ImportResolver:
    async def resolve(self, store: GraphStore,
                      changed_files: list[str] | None = None) -> ResolveStats: ...
```

- Build a module index from the graph: map each File node's module path
  (derived from its path, e.g. `src/app/auth.py` → `app.auth`) → file id,
  and its exported top-level def names → symbol ids.
- For each File node's `attrs["imports"]`: if the module resolves to a repo
  File, emit an **IMPORTS** edge (File → File) with `source=resolved`;
  external modules (stdlib, third-party) get an **IMPORTS** edge to a
  generated `Package` node marked `attrs["external"]=true` so the edge has a
  real endpoint. (feat-003's Kuzu adapter drops edges to absent nodes, so
  the target node is always materialized first.)
- For each caller node's `attrs["refs"]`: resolve the name against (1) local
  defs in the same file, (2) the file's resolved imports. Exactly one match
  → **CALLS** edge (caller → callee), `source=resolved`. Zero or many → no
  edge; tally in stats and stash candidates in caller `attrs["unresolved"]`.
  (Never fabricate a confident edge — ADR-0004/spec §3.)
- All new edges written via `store.add(...)` (not file-bound; survive
  `delete_file`). Re-running is idempotent — resolve only adds edges that
  don't exist, keyed by `(src,dst,kind)`. `changed_files` (feat-004) scopes
  the work; `None` = whole graph.

### 4.7 `IngestPipeline` + `CodeGraph` (`pipeline.py`, `codegraph.py`)

```python
class IndexReport(BaseModel):
    files_indexed: int; nodes: int; edges: int
    by_node_kind: dict[str, int]; by_edge_kind: dict[str, int]
    skipped: list[str]; resolve: ResolveStats

class IngestPipeline:
    async def run(self, repo: RepoSource, store: GraphStore,
                  packs: list[LanguagePack]) -> IndexReport: ...

class CodeGraph:                       # the top-level user facade (spec §4.1)
    @classmethod
    async def index(cls, repo_path=".", languages=None, config=None) -> "CodeGraph": ...
    @classmethod
    async def open(cls, repo_path=".", config=None) -> "CodeGraph": ...   # delegates to Store.open
    @property
    def store(self) -> Store: ...
    def stats(self) -> IndexReport: ...
```

- `run`: for each `SourceFile` from `repo.iter_files`, pick the pack, build
  a `TreeSitterExtractor`, `extract`, `store.upsert(subgraph)`. Extraction
  is CPU-bound and file-isolated → run in a thread pool
  (`asyncio.to_thread`) with bounded concurrency; upserts are serialized by
  the store's own lock. After all files, run `ImportResolver.resolve`.
- `CodeGraph.index` composes `Store.open` (feat-003) + `IngestPipeline`,
  resolves which packs from `languages` (default: every builtin pack whose
  extension appears in the repo). `CodeGraph.open` is the deferred-from-003
  read path. The `commit` for provenance is read from git HEAD if present,
  else `""`.

### 4.8 CLI (`cli.py`, wired into `main.py`)

`ckg index [PATH] [--lang ...] [--include GLOB] [--exclude GLOB]
[--config ckg.yaml]` → runs `CodeGraph.index`, prints the `IndexReport`
(files, nodes/edges by kind, unresolved count, skipped). Replaces the
scaffold `main.py`'s single-task behaviour with an argparse subcommand
dispatcher (`index` now; `serve-mcp` etc. land in feat-008). This removes
`main.py` from the coverage-omit list — the new `index` command is covered
by a CLI smoke test against a tmp fixture repo.

### 4.9 Configuration

Reads the `ingest:` block already in `ckg.yaml` (languages, exclude,
max_file_kb, lsp_assist) via a new `IngestConfig` section in
`agentforge_graph/config.py` (same lenient loader as `StoreConfig`).
`lsp_assist` is parsed but inert at 0.1.

## 5. Alternatives considered

| Option | Why not |
|---|---|
| `tree_sitter_language_pack.get_parser()` | Returns ABI-incompatible `builtins.Node`; use `Parser(get_language())` (framework note 2026-06-12). |
| Emit candidate cross-file edges in pass 1 with best-guess ids | Forces fabricated/*maybe-invalid* symbol ids and edges to absent nodes (Kuzu drops them). Storing refs as node `attrs` keeps every edge endpoint real and centralizes resolution in pass 2. |
| One bespoke extractor per language | Edge semantics drift per language (the cognee Python-only trap). Shared harness + per-pack `.scm` keeps `CALLS` uniform. |
| Ship all 10 packs in this PR | Unreviewable; spec says packs are independently mergeable. Python first, rest as follow-ups over the same harness. |
| Compiler/LSP extraction for precision | ADR-0002 — kills the "index any repo, no build" property. |
| Resolve calls to confident edges on ambiguity | Violates ADR-0004; we record candidates, never guess. |

## 6. Migration / rollout

Greenfield. Adding a language = a new `packs/<lang>/` dir + registry entry
(one follow-up PR each), no pipeline change. Re-indexing is upsert-per-file
(feat-003 transactional) + a resolve pass; feat-004 will scope both to the
changed set. Grammar versions are pinned via the `engine` extra; golden
fixtures catch grammar drift.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Descriptor nesting / overloads fiddly per language | feat-001 `Descriptor` + `(+N)` rule centralizes the grammar; per-pack golden fixtures gate correctness; Python only in this PR. |
| Import resolution false positives | Resolve only on a *unique* match; ambiguous → no edge, recorded. `resolved` vs `parsed` provenance keeps it honest. |
| tree-sitter / language-pack version churn | Standalone-parser workaround pinned + documented; golden files catch query breakage in CI. |
| CPU-bound extraction blocks the loop | `asyncio.to_thread` with bounded concurrency; per-file isolation makes it embarrassingly parallel. |
| Module-path inference (path → dotted module) is Python-specific | Lives in the *pack* (resolver asks the pack to map path↔module), not the core resolver, so other packs override it. |
| `main.py` rewrite touches scaffold-managed file | It's already forked (pyproject is); keep the change minimal and covered. |

## 8. Open questions (decisions for review)

1. **Languages in this PR?** Proposed: **Python only** (spec metadata +
   independently-mergeable packs). The other nine are follow-up PRs.
2. **Resolution depth?** Proposed: **full Tier-A for Python** — import
   resolution + unique-match call resolution; ambiguous/cross-package calls
   stay recorded-not-guessed. (Not structural-only.)
3. **`CodeGraph` facade here?** Proposed: **yes** — feat-003 deferred
   `CodeGraph.open` to feat-002; this is where `index()` lives, so the
   facade belongs here.
4. **Rewrite `main.py` into a subcommand CLI now?** Proposed: **yes** — adds
   `ckg index` and lets us drop the coverage-omit on `main.py`.

## 9. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-12 | Parse via `Parser(get_language())`, not `get_parser()` | language-pack 1.8.1 bundles an ABI-incompatible parser (framework note) |
| 2026-06-12 | Pass-1 records imports/refs as node `attrs`; pass-2 makes the edges | Keeps every edge endpoint a real symbol id; centralizes cross-file resolution; Kuzu drops edges to absent nodes |
| 2026-06-12 | Python-only in this PR; packs are follow-up PRs | Spec metadata + "independently mergeable unit"; reviewable increment |
| 2026-06-12 | Capture-name convention shared across packs | `CALLS`/`CONTAINS` mean the same in every language; extractor keys off capture names, not node types |
| 2026-06-12 | path↔module mapping lives in the pack, not core resolver | It's language-specific (Python dotted modules ≠ Go packages) |
| 2026-06-12 | Rewrite `main.py` into an argparse subcommand dispatcher | Ships `ckg index`; removes the coverage-omit on main.py |
| 2026-06-12 | External imports get a generated `Package` node | IMPORTS edge needs a real endpoint; marks `external=true` |

## 10. Chunk plan (the single feat-002 PR)

| Chunk | Commit | Contents |
|---|---|---|
| 0 | `chore(002): ingest config + fixtures` | `IngestConfig` in config.py; `tests/ingest/fixtures/python/` sample repo |
| 1 | `feat(002): repo source + pack abstraction` | `source.py` (RepoSource, SourceFile build, excludes/limits), `pack.py` (LanguagePack, registry) |
| 2 | `feat(002): python pack + tree-sitter extractor` | `packs/python/*.scm` + pack, `extractor.py` (pass 1: nodes, CONTAINS, imports/refs as attrs); passes `ExtractorConformance` + golden test |
| 3 | `feat(002): import & call resolver` | `resolver.py` (pass 2), `report.py` (IndexReport, ResolveStats) |
| 4 | `feat(002): ingest pipeline + CodeGraph` | `pipeline.py`, `codegraph.py` (index/open), `__init__` exports |
| 5 | `feat(002): ckg index CLI` | `cli.py`, rewrite `main.py` to argparse dispatch; drop main.py coverage-omit |
| 6 | `test(002): pipeline, resolver, layering, CLI smoke` | end-to-end index of the fixture repo; resolver cases; layering; CLI smoke |
| 7 | `docs(002): impl status + tracker; design accepted` | spec status; TRACKER; this doc → accepted; framework note already added |

## 11. References

- Spec: `docs/features/feat-002-tree-sitter-ingestion.md`
- ADRs: 0001 (layering), 0002 (tree-sitter over compiler), 0003 (symbol
  IDs), 0004 (provenance)
- feat-001 (`Extractor`/`ExtractorConformance`, `SymbolID`/`Descriptor`),
  feat-003 (`Store`/`GraphStore.upsert`/`add`)
- Framework note:
  `docs/framework/2026-06-12-tree-sitter-language-pack-bundles-incompatible-parser.md`
- Prior art: stack-graphs (declarative rules, file-incremental), Blarify
  (two-tier resolution), SCIP descriptor conventions.
