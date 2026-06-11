# ADR-0003: Stable SCIP-style symbol IDs + per-file subgraphs

## Metadata

| Field | Value |
|---|---|
| **Number** | 0003 |
| **Title** | Stable SCIP-style symbol IDs + per-file subgraphs as the incrementality foundation |
| **Status** | Accepted |
| **Date** | 2026-06-11 |
| **Deciders** | kjoshi |
| **Tags** | architecture, identity, incrementality |

---

## 1. Context and problem statement

An agent's working memory over a repo that changes many times an hour
is only useful if it stays fresh, and a full re-index per commit makes
freshness unaffordable. The research showed this is the dividing line
between toy and production CKGs: Sourcegraph's LSIF predecessor used
opaque numeric graph IDs with global ordering constraints that made
incremental indexing impossible — SCIP was created specifically to fix
this with stable string symbol IDs; stack-graphs made indexing
file-incremental by building each file's subgraph in isolation. How do
we identify nodes and structure extraction so that re-indexing costs
scale with the size of a change, not the size of the repo — and so that
enrichments attached to unchanged code survive edits nearby?

## 2. Decision drivers

- Re-index cost must be proportional to the diff (ADR-0002's
  fast-parsing only pays off if we don't redo everything).
- Enrichments (summaries, pattern tags, ADR links) are expensive and
  must not be orphaned when an unrelated symbol in the same file
  changes.
- Identity must be deterministic and order-independent so per-file
  extraction can run in parallel and merge.
- A temporal layer (feat-009) needs the *same* symbol to keep its
  identity across commits to track history.

## 3. Considered options

1. **Opaque/auto-increment node IDs** (LSIF-style, DB primary keys).
2. **Content-hash node IDs** (hash of the symbol's source text).
3. **Stable descriptor-based symbol IDs** (SCIP-style:
   `ckg <lang> <repo> <path> <descriptor>`) + per-file subgraphs as
   the unit of ingestion/deletion.

## 4. Decision outcome

**Chosen: Option 3 — SCIP-style descriptor symbol IDs + per-file
subgraphs.** Every node's ID is a human-readable string derived from
(language, repo, path, descriptor), where descriptors follow SCIP
grammar (`Type#`, `method().`, `term.`). No global counters, no
ordering constraints. Extraction produces one `FileSubgraph` per file
keyed by `(path, content_hash)`; cross-file resolution is a separate
pass. Incremental re-index (feat-004) is then a thin orchestration:
re-extract changed files, swap their subgraphs transactionally,
re-resolve only the dirty import-graph region.

### Positive consequences

- Re-index touches only changed files; embeddings/enrichments
  recompute only for dirty symbols.
- Unchanged symbols keep their ID across edits → their enrichments
  survive (content-hash IDs would not: any edit changes the hash).
- Parallel, order-independent extraction; deterministic graphs
  (testable by isomorphism).
- Cross-commit identity gives feat-009 history for free.

### Negative consequences (trade-offs)

- Descriptor rules are fiddly per language (overloads, anonymous
  functions, generics) — mitigated by adopting SCIP's conventions and
  a disambiguator suffix.
- A rename changes the descriptor, so it reads as delete+add and
  orphans enrichments on the renamed symbol; feat-009 may add rename
  lineage via git similarity later.

## 5. Pros and cons of the options

### Option A: Opaque/auto-increment IDs
- + Trivial to generate.
- − Unstable across re-index; forces whole-repo reindex; the exact
  trap SCIP replaced LSIF to escape.

### Option B: Content-hash IDs
- + Stable for *identical* text; natural change detection.
- − Any edit (even a comment) changes identity → orphans every
  enrichment on touched code; same symbol gets a new ID each edit.

### Option C: Descriptor symbol IDs + per-file subgraphs
- + Stable across edits, deterministic, order-independent,
  incremental-ready, history-ready.
- − Descriptor grammar work per language.

## 6. References

- feat-001 (symbol-ID scheme), feat-002 (per-file extraction),
  feat-004 (incremental), feat-009 (temporal).
- Research §2.3 (SCIP vs LSIF — verified), §2.4 (stack-graphs
  file-incremental — verified), §3.2.
- SCIP symbol grammar; stack-graphs paper (arxiv 2211.01224).
- Related: ADR-0002, ADR-0005.
