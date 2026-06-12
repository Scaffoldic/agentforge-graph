# feat-002: Tree-sitter ingestion pipeline

## Metadata

| Field | Value |
|---|---|
| **ID** | feat-002 |
| **Title** | Tree-sitter ingestion pipeline (per-language extraction + cross-file resolution) |
| **Status** | proposed |
| **Owner** | kjoshi |
| **Created** | 2026-06-11 |
| **Target version** | 0.1.0 |
| **Languages** | python |
| **Module package(s)** | `agentforge_graph.ingest` |
| **Depends on** | feat-001 |
| **Blocks** | feat-004, feat-005, feat-007, feat-011 |

---

## 1. Why this feature

The graph is only as good as what gets into it. The survey showed a
hard fork in parsing strategy: compiler-grade extraction (CodeQL,
SCIP indexers, Glean) is precise but **requires a working build
toolchain per project** — a non-starter for an agent that must index
any repo it is pointed at. Tree-sitter extraction (stack-graphs,
cognee, Blarify, Potpie) needs zero configuration and no build, at
the cost of heuristic cross-file resolution.

We take the tree-sitter path, with the two mitigations the better
tools use: a declarative per-language rule layer (stack-graphs'
`tree-sitter-graph` insight: language rules written once, no
per-project config) and a separate resolution pass that upgrades
heuristic references to resolved edges (Blarify's tree-sitter + LSP
two-tier model).

## 2. Why it must ship in the agent core

- **One extraction pipeline, N languages.** If each language were a
  bespoke script, edge semantics would drift per language (cognee's
  Python-only trap, research §2.6). A shared `Extractor` harness +
  per-language query packs keeps `CALLS` meaning the same thing in
  Python and TypeScript.
- **The per-file subgraph discipline lives here.** feat-004's
  incrementality depends on extraction being file-isolated (no
  cross-file visibility during extract). That constraint must be
  enforced by the pipeline, not promised by convention.
- **Framework extractors (feat-011) ride on this.** They are extra
  query packs over the same parse trees — only possible if parsing is
  centralized.

## 3. How consumers benefit

- Point the agent at any repo: `ckg index .` works with no build, no
  compile_commands.json, no language server install — the property
  that made stack-graphs viable for every repo on GitHub.
- Adding language N+1 is one query-pack file (tree-sitter queries +
  descriptor rules), not a new pipeline.
- Downstream features get resolution *quality labels* for free:
  `source="parsed"` (syntactic candidate) vs `source="resolved"`
  (import-graph-confirmed), so retrieval can prefer precise edges.

## 4. Feature specifications

### 4.1 User-facing experience

```python
from agentforge_graph import CodeGraph

graph = await CodeGraph.index(
    repo_path=".",
    languages=["python", "typescript"],   # default: auto-detect
)
print(graph.stats())   # files, nodes, edges by kind, unresolved refs
```

CLI: `ckg index [PATH] [--lang ...] [--include/--exclude GLOB]`.

### 4.2 Public API / contract

```python
class LanguagePack(BaseModel):
    language: str                       # "python"
    grammar: str                        # tree-sitter grammar pkg
    structure_queries: str              # .scm: defs, classes, imports
    reference_queries: str              # .scm: calls, attribute refs
    descriptor_rules: DescriptorRules   # symbol-ID descriptor mapping

class TreeSitterExtractor(Extractor):   # feat-001 ABC
    def __init__(self, pack: LanguagePack): ...
    def extract(self, file: SourceFile) -> FileSubgraph: ...

class ImportResolver:
    """Pass 2: upgrade candidate references using the import graph."""
    async def resolve(self, store: GraphStore,
                      changed_files: list[str] | None = None) -> ResolveStats: ...

class IngestPipeline:
    async def run(self, repo: RepoSource, store: GraphStore,
                  packs: list[LanguagePack]) -> IndexReport: ...
```

**v0.1 language packs (top 10 by usage):** Python, TypeScript,
JavaScript, Java, Go, C#, Rust, Ruby, PHP, C++. Two **support tiers**
so we promise only what tree-sitter can honestly deliver:

- **Tier A — structure + import resolution** (Python, TypeScript,
  JavaScript, Java, Go, C#, Rust, Ruby, PHP): full pass-1 extraction
  plus confident pass-2 resolution of `CALLS`/`IMPORTS` from the
  import graph.
- **Tier B — structure + heuristic refs** (C++): nodes, `CONTAINS`,
  and `IMPORTS`/`#include` edges extracted; call resolution is
  best-effort because the preprocessor, templates, and overloads
  defeat pure tree-sitter — refs stay `parsed`, and `resolved` edges
  only appear via opt-in LSP-assist. We ship honest `parsed`-only
  refs rather than fabricate confident `resolved` edges.

**v0.2 candidates:** Kotlin, Swift, C, Scala. Pack files live in
`agentforge_graph/ingest/packs/<lang>/`; JS and TS share a grammar
family, so the marginal cost of that pair is low.

### 4.3 Internal mechanics

Two-pass design (stack-graphs-style):

1. **Extract (parallel, file-isolated).** Parse with tree-sitter; run
   structure queries → `File`/`Class`/`Function`… nodes with
   `CONTAINS` edges; run reference queries → `IMPORTS` edges and
   *candidate* `REFERENCES` edges (`dst` = best-guess symbol IDs from
   the file's own imports + local scope). No cross-file reads. Output
   one `FileSubgraph` keyed by `(path, content_hash)`.
2. **Resolve (cheap, graph-only).** Walk the import graph in the
   store; for each candidate reference, if exactly one imported
   symbol matches the descriptor, rewrite to a `CALLS`/`REFERENCES`
   edge with `source="resolved"`. Ambiguous candidates stay
   `parsed` with all candidates in `attrs.candidates`.

Properties this guarantees:
- Extraction parallelizes trivially (per file).
- Re-running resolve is idempotent and touches only edges, so
  feat-004 can re-resolve just the dirty region.
- Precision is honest: we never fabricate a confident call edge from
  a dynamic-dispatch guess (the known tree-sitter weakness, research
  §1) — ambiguity is recorded, not hidden.

Optional **LSP assist** (post-0.1, behind config): for languages with
cheap LSP servers, batch-resolve ambiguous references via
`textDocument/definition` — Blarify's model. Off by default.

### 4.4 Module packaging

`agentforge_graph.ingest`; grammar wheels pulled via extras:
`pip install agentforge-graph[python,typescript]`.

### 4.5 Configuration

```yaml
ingest:
  languages: auto          # or explicit list
  exclude: ["**/node_modules/**", "**/.venv/**", "**/dist/**"]
  max_file_kb: 512         # skip generated monsters; logged, never silent
  lsp_assist: off
```

## 5. Plug-and-play & upgrade story

Language packs are entry-point discoverable
(`agentforge_graph.packs`), so third-party packs install as separate
pip packages without touching core.

## 6. Cross-language parity

n/a (agent is Python; *indexed* languages are the pack list above).

## 7. Test strategy

- Golden-file tests per pack (10 packs at v0.1): fixture repo →
  expected `FileSubgraph` JSON (committed), diffed on every change.
  Tier B packs (C++) assert structural-only output and `parsed`-only
  refs, so absent resolution is a passing state, not a silent gap.
- Property test: extraction determinism (same content hash → same
  subgraph, any file order).
- Resolution tests: known import shapes (absolute, relative,
  re-export, `__init__` star) per language.
- Conformance: every pack runs the feat-001 `Extractor` suite.
- Scale smoke test: index a real mid-size OSS repo in CI; assert node
  counts within tolerance and wall-clock budget.

## 8. Risks & open questions

| Risk / Question | Mitigation / Decision |
|---|---|
| Call-edge precision on dynamic languages is inherently limited | Honest provenance (`parsed` vs `resolved`); LSP assist as opt-in escalation; never silently guess |
| Tree-sitter grammar version churn breaks queries | Pin grammar versions per pack; golden files catch drift in CI |
| Descriptor rules per language are fiddly | Steal SCIP's per-language descriptor conventions wholesale |
| Monorepos with mixed build roots | Repo→Package detection via marker files (pyproject, package.json); packages are just nodes, no build semantics |
| 10 language packs in v0.1 is large scope; quality varies sharply by language | Two-tier support (Tier A resolution vs Tier B structural-only); per-pack golden fixtures gate quality independently, so a weak pack ships honestly degraded, not blocking the others. Packs are independently mergeable units of work (see tracker) |

## 9. Out of scope

- Compiler/build-based extraction (CodeQL-style). Rejected for 0.x:
  kills the "index anything" property.
- Binary / bytecode analysis (Joern territory).
- Data-flow analysis.
- Watch mode / daemonized re-index (feat-004 owns change detection).

## 10. References

- Research §2.4 (stack-graphs: declarative rules, file-incremental),
  §2.9 (Blarify two-tier), §2.11 (tree-sitter indexer family).
- feat-001 (contracts), feat-004 (incremental), feat-011 (framework
  packs extend this pipeline).

---

## Implementation status

**Shipped (Python pack)** — design:
`docs/design/design-002-tree-sitter-ingestion.md` (accepted).
`agentforge_graph.ingest` ships the full pipeline for **Python (Tier A)**:

- `RepoSource` (file discovery, excludes/includes, size limit, hashing) +
  `LanguagePack`/`PackRegistry` + the Python pack (`structure.scm` /
  `references.scm`).
- `TreeSitterExtractor` (pass 1): File/Class/Function/Method nodes with
  nested SCIP descriptors + `CONTAINS`; method promotion; `(+N)` overloads;
  imports/refs recorded as node attrs. Passes `ExtractorConformance`.
- `ImportResolver` (pass 2): `IMPORTS` (in-repo + external `Package` nodes)
  and unique-match `CALLS`; ambiguous/external-only calls left unresolved
  and tallied (never guessed). `parsed` vs `resolved` provenance.
- `IngestPipeline` (threaded extract → upsert → resolve) + `CodeGraph`
  facade (`index`/`open`/`stats`) + the **`ckg index`** CLI (rewrote the
  scaffold `main.py`).
- 64 tests for this feature; whole-package coverage ~98% (≥90 floor),
  `mypy --strict`, ruff. CI runs `--extra engine`.

**Follow-up PRs** (same harness): the other nine packs — ts, js, java, go,
c#, rust, ruby, php (Tier A) and c++ (Tier B). **Deferrals** (design §3/§8):
LSP-assist; incremental/watch (feat-004); cross-run edge-dedup in resolve
(feat-004 will scope + clear). Parser/query objects are rebuilt per file for
thread-safety — a parser pool is a later optimization.
