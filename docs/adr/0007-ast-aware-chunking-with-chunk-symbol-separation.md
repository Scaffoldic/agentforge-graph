# ADR-0007: AST-aware chunking with chunk↔symbol separation

## Metadata

| Field | Value |
|---|---|
| **Number** | 0007 |
| **Title** | AST-aware chunking, with chunks linked to (not conflated with) symbols |
| **Status** | Accepted |
| **Date** | 2026-06-11 |
| **Deciders** | kjoshi |
| **Tags** | architecture, retrieval, chunking |

---

## 1. Context and problem statement

Vector search is how an agent enters the graph from a natural-language
question, and chunking quality caps retrieval quality. Two coupled
decisions: (a) *how* to split code into embeddable units, and (b)
*how* chunks relate to the graph. Line-based chunking splits functions
mid-body and fuses unrelated declarations; the cAST research reports
measurable retrieval and end-to-end gains from AST-aware chunking
(unverified numbers, but directionally uncontested). Separately,
a verified schema-driven CKG design keeps chunks as distinct node types
linked to semantic entities rather than treating a chunk as the entity.
How do we
chunk code for embeddings, and how do chunks sit in the graph?

## 2. Decision drivers

- Retrieved units must be syntactically whole and pasteable (no
  half-functions).
- A vector hit must lead into the graph (to its symbol, callers,
  class) — that join is the value of having a graph at all (feat-006).
- Embeddings are the largest steady-state cost; re-embedding must be
  incremental (only dirty symbols).
- Chunking must work across all 10 languages via the same mechanism.

## 3. Considered options

1. **Line/fixed-size chunks, chunk = node** — chunk is the unit of
   both retrieval and graph.
2. **AST-aware chunks, chunk = node** — better boundaries, but chunks
   still are the graph nodes.
3. **AST-aware chunks, chunk linked to symbol nodes** — cAST split/
   merge; chunks are a separate node type with `CHUNK_OF` edges to
   the functions/classes they cover.

## 4. Decision outcome

**Chosen: Option 3 — AST-aware (cAST) chunking + chunk↔symbol
linking.** The chunker recursively splits oversized AST nodes and
greedily merges small siblings under a token budget, never splitting
inside a function unless the function alone exceeds the budget. Chunks
are `Chunk` nodes (separate from `Function`/`Class`) connected by
`CHUNK_OF` edges, embedded into the vector store keyed by content
hash. A vector hit therefore returns its symbol IDs directly, and
re-embedding drains the feat-004 dirty set so only changed symbols
recompute. The chunker is grammar-driven, so all 10 languages flow
through the same code.

### Positive consequences

- Whole, pasteable retrieval units; no signature/body splits.
- Every hit is one step from "similar text" to "the function and its
  neighborhood" — the graph join feat-006 depends on.
- Incremental re-embedding by content hash → cents per diff, not
  dollars.

### Negative consequences (trade-offs)

- cAST's reported gains are unverified for our corpus; mitigated by a
  retrieval smoke metric and keeping `Chunker` an ABC (swappable).
- Token counting needs a tokenizer; we use a fixed fast tokenizer for
  budgeting only (consistency over exactness).

## 5. Pros and cons of the options

### Option A: Line chunks, chunk = node
- + Trivial to implement.
- − Splits functions; fuses unrelated code; no clean symbol join;
  poor retrieval.

### Option B: AST chunks, chunk = node
- + Good boundaries.
- − Conflates retrieval artifact with semantic entity; a large
  function becomes multiple "entities"; muddies the graph and
  enrichment targets.

### Option C: AST chunks linked to symbols
- + Good boundaries *and* clean graph join; incremental-friendly;
  enrichment targets stay semantic.
- − Slightly more schema (bipartite chunk/symbol); unverified metric
  gains.

## 6. References

- feat-005 (cAST chunker, `CHUNK_OF`), feat-006 (consumes the join).
- Research §3.1 (cAST — unverified metrics; schema-driven CKG
  chunk↔symbol separation — verified), §2.6. cAST paper: arxiv 2506.15655.
- Related: ADR-0008 (retrieval), ADR-0003 (content-hash incremental).
