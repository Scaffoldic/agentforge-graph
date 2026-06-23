# ADR-0002: Tree-sitter (no-build) extraction over compiler-grade analysis

## Metadata

| Field | Value |
|---|---|
| **Number** | 0002 |
| **Title** | Tree-sitter (no-build) extraction over compiler-grade analysis |
| **Status** | Accepted |
| **Date** | 2026-06-11 |
| **Deciders** | kjoshi |
| **Tags** | architecture, parsing, ingestion |

---

## 1. Context and problem statement

The graph is only as good as what we can extract from source, and the
research survey showed a hard fork in how CKG tools parse. Compiler-
grade tools (curated rule-pack analyzers, descriptor-based indexers,
server-based fact-indexing systems) get precise
semantics — real type resolution, accurate call graphs — but require a
**working build toolchain per project** (javac, a configured C/C++
compiler, cargo). Syntactic tools (file-incremental name-resolution
designs, schema-driven CKG designs, tree-sitter-based indexers,
agent-oriented code tools) parse with tree-sitter: zero configuration, no build,
at the cost of heuristic cross-file resolution. How should
agentforge-graph parse code if it must index *any* repo an agent is
pointed at, including ones that don't build on the indexing machine?

## 2. Decision drivers

- "Index anything" is a hard requirement: an agent points at a repo
  and it must index without per-project build setup or network access
  to dependencies.
- Indexing must be fast and incremental (ADR-0003); compiler-grade
  extraction is slow and whole-program.
- We serve LLM retrieval, not security taint analysis — approximate
  call edges are acceptable if their uncertainty is *recorded*
  (ADR-0004), not hidden.
- We want breadth across 10 languages (ADR-0009); compiler frontends
  are per-language heavyweight integrations.

## 3. Considered options

1. **Compiler-grade** — per-language compiler frontends (curated
   rule-pack / descriptor-based model).
2. **Tree-sitter only** — pure syntactic extraction.
3. **Tree-sitter + optional LSP-assist** — syntactic by default,
   escalate ambiguous references to a language server when available.

## 4. Decision outcome

**Chosen: Option 3 — tree-sitter by default, LSP-assist opt-in.**
Extraction uses tree-sitter with declarative per-language query packs
(the file-incremental name-resolution insight: language rules written
once, no per-project config). A separate, cheap resolution pass upgrades heuristic
references to resolved edges using the import graph. For languages
where syntax is insufficient (notably C++), an opt-in LSP-assist pass
resolves the remainder. We never require a build to index.

### Positive consequences

- Any repo indexes with no build, no compile DB, no language-server
  install — the property that made file-incremental name-resolution
  designs viable at large scale.
- Adding a language is one query-pack file, not a compiler
  integration.
- Fast and naturally file-incremental (ADR-0003 builds on this).

### Negative consequences (trade-offs)

- Call-edge precision on dynamic dispatch / templates / macros is
  inherently limited; mitigated by honest provenance (ADR-0004) and
  the A/B tier split (ADR-0009), never by guessing.
- No data-flow / control-flow analysis (the code-property-graph /
  data-flow tools' domain) — explicitly out of scope for 0.x.

## 5. Pros and cons of the options

### Option A: Compiler-grade
- + Precise types, accurate call graphs, framework taint models.
- − Requires per-project builds; slow; whole-program; kills "index
  anything"; per-language heavyweight.

### Option B: Tree-sitter only
- + Zero-config, fast, broad, incremental.
- − Leaves every ambiguous reference unresolved with no escalation
  path.

### Option C: Tree-sitter + LSP-assist
- + All of B's wins, with a precision escape hatch where it matters.
- − Two code paths; LSP servers are per-language ops when enabled.

## 6. References

- feat-002 (ingestion pipeline, two-pass design, A/B tiers).
- Research §2.2 (compiler-grade build requirement), §2.4
  (file-incremental declarative rules), §2.9 (tree-sitter+LSP indexers).
- Related: ADR-0003 (incrementality), ADR-0004 (provenance),
  ADR-0009 (language tiers).
