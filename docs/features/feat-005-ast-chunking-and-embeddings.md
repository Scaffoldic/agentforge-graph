# feat-005: AST-aware chunking & embeddings

## Metadata

| Field | Value |
|---|---|
| **ID** | feat-005 |
| **Title** | AST-aware chunking & embeddings (chunk ↔ symbol linking) |
| **Status** | proposed |
| **Owner** | kjoshi |
| **Created** | 2026-06-11 |
| **Target version** | 0.1.0 |
| **Languages** | python |
| **Module package(s)** | `agentforge_graph.chunking`, `agentforge_graph.embed` |
| **Depends on** | feat-002, feat-003 |
| **Blocks** | feat-006, feat-010 |

---

## 1. Why this feature

Vector search is how an agent *enters* the graph — natural-language
question → relevant code region — and chunking quality directly caps
retrieval quality. Line-based chunking splits functions mid-body and
glues unrelated declarations together; the cAST paper measured the
cost (reported +4.3 Recall@5 on RepoEval and +2.67 Pass@1 on
SWE-bench for AST-aware over line-based chunking — unverified in our
sweep, but directionally uncontested across sources).

Equally important is cognee's verified schema insight: chunks are
**linked to** symbol nodes (`CodePart`/`SourceCodeChunk` as separate
node types), not conflated with them. A chunk is a retrieval
artifact; a function is a semantic entity. Keeping them distinct is
what lets a vector hit expand into the graph (feat-006).

## 2. Why it must ship in the agent core

- The chunk↔symbol bipartite structure is schema (feat-001 reserved
  `Chunk` + `CHUNK_OF`); only the core pipeline can guarantee every
  chunk carries valid symbol links and provenance.
- Embedding spend is the largest steady-state cost of the system.
  Incremental recomputation (only dirty symbols re-embed) requires
  integration with feat-004's `DirtySet` — impossible if chunking
  lived outside the pipeline.
- One chunker serving code *and* docs (feat-010 reuses it for
  markdown/ADRs with a heading-based splitter) keeps retrieval
  uniform.

## 3. How consumers benefit

- Chunks never split a function signature from its body and never
  fuse two unrelated top-level definitions — retrieval results are
  pasteable, syntactically whole units.
- Every vector hit comes back with symbol IDs attached: one call from
  "similar text" to "the function, its callers, its class" —
  no separate lookup, no path string parsing.
- Re-embedding after a typical diff costs cents, not dollars: only
  chunks whose symbols are in the `DirtySet` recompute.

## 4. Feature specifications

### 4.1 User-facing experience

```python
await graph.embed()                  # chunk + embed everything indexed
hits = await graph.search("where do we validate JWT tokens", k=8)
# hits: [ScoredChunk(text, score, symbol_ids, path, span)]
```

### 4.2 Public API / contract

```python
class Chunker(ABC):
    @abstractmethod
    def chunk(self, file: SourceFile, subgraph: FileSubgraph) -> list[Chunk]

class CASTChunker(Chunker):
    """Split-then-merge over the tree-sitter AST."""
    def __init__(self, max_tokens: int = 512, min_tokens: int = 64): ...

class Embedder(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]

class EmbedPipeline:
    async def run(self, store: Store, scope: DirtySet | Literal["all"]) -> EmbedReport
```

`Chunk` node attrs: `text`, `token_count`, `path`, `span`,
`content_hash`. Edges: `CHUNK_OF → Function|Class|File` (one chunk
may cover several small symbols; a large symbol may own several
chunks, ordered via `attrs.seq`).

### 4.3 Internal mechanics

**Chunking (cAST split-then-merge, research §3.1):**

1. Walk the AST top-down; any node ≤ `max_tokens` is a candidate
   chunk; oversized nodes recurse into children (a 900-token class
   becomes per-method chunks, each prefixed with the class signature
   line for context).
2. Greedily merge adjacent small siblings (imports, constants,
   one-liners) up to `max_tokens`, never across a top-level
   definition boundary.
3. Emit `CHUNK_OF` edges by intersecting chunk spans with symbol
   spans from the `FileSubgraph` (already in hand — no re-parse).

**Embedding text format:** `<path> | <qualified symbol> \n <code>` —
path/symbol prefix measurably helps code retrieval and costs a few
tokens.

**Incrementality:** chunk `content_hash` keys the vector store;
`EmbedPipeline` drains `DirtySet(consumer="embeddings")`, deletes
vectors `where path IN changed`, re-embeds new hashes only. Before
feat-004 ships, `scope="all"` with hash-skip gives coarse
incrementality (unchanged chunk hash → skip).

**Embedder drivers at 0.1:** `fastembed` (local, default — no API
key needed) and `voyage` / `openai`-compatible HTTP (config).
Batching, rate-limit retry, and cost accounting via AgentForge's
provider rails.

### 4.4 Module packaging

`agentforge_graph.chunking` + `agentforge_graph.embed` — default
install; `fastembed` as default extra.

### 4.5 Configuration

```yaml
chunking:
  max_tokens: 512
  min_tokens: 64
embed:
  driver: fastembed            # fastembed | voyage | openai-compat
  model: code-default          # driver-specific resolution
  batch_size: 64
```

## 5. Plug-and-play & upgrade story

Changing `embed.model` flags every vector stale (model name is part
of the vector-store namespace) → next `embed()` rebuilds. Chunker
parameter changes likewise (params hashed into chunk namespace). No
silent mixed-model indexes.

## 6. Cross-language parity

n/a.

## 7. Test strategy

- Property: chunk set covers every non-whitespace line exactly once;
  no chunk exceeds `max_tokens`; no chunk splits inside a function
  body unless the function alone exceeds `max_tokens`.
- Golden: fixture files → expected chunk boundaries per language.
- Linking: every chunk has ≥1 `CHUNK_OF` edge; span-intersection
  correctness on nested classes.
- Retrieval smoke (env-gated live): seeded Q→expected-symbol pairs on
  a fixture repo; assert Recall@5 above a floor — guards chunker
  regressions with a behavioral metric.

## 8. Risks & open questions

| Risk / Question | Mitigation / Decision |
|---|---|
| cAST numbers unverified; gains may be smaller for us | The retrieval smoke test gives us our own metric; chunker is an ABC so alternatives are swappable |
| Token counting needs a tokenizer (model-dependent) | Use a fixed fast tokenizer (e.g. cl100k-compatible) for *budgeting* only; exactness doesn't matter, consistency does |
| Local fastembed quality vs hosted code-embedding models | Default favors zero-config; config flips to hosted. Document the tradeoff, benchmark both on the smoke set |
| Chunker AST quality across the 10 v0.1 languages | Chunker is grammar-driven, so it inherits feat-002's language packs automatically; per-language golden boundary tests run for all 10; within an oversized node lacking a grammar rule it falls back to line-based split (logged, never silent) |
| Docstrings: embed with code or as separate doc chunks? | With code at 0.1 (they share the AST node); feat-010 may additionally surface them as `DocChunk`s |

## 9. Out of scope

- Embedding non-code artifacts (markdown, ADRs, commits) — feat-010,
  which reuses `Chunker` with a markdown strategy.
- Reranking and graph expansion at query time — feat-006.
- Summaries-as-chunks (feat-012 emits `Summary` nodes that feat-006
  may index, but generation lives there).

## 10. References

- Research §3.1 (cAST split/merge — unverified metrics; cognee
  chunk↔symbol separation — verified), §2.6.
- cAST paper: arxiv.org/abs/2506.15655.
- feat-002 (FileSubgraph spans), feat-003 (VectorStore), feat-004
  (DirtySet), feat-006 (consumer).

---

## Implementation status

**Shipped (Python; Bedrock embeddings)** — design:
`docs/design/design-005-ast-chunking-and-embeddings.md` (accepted).
`agentforge_graph.chunking` + `agentforge_graph.embed` ship:

- **`CASTChunker`** — split-then-merge over the symbol spans feat-002
  extracted (no re-parse): a symbol that fits is never split or fused;
  oversized symbols recurse (class → per-method → line windows); gaps merge
  up to budget. `Chunk` → `CHUNK` nodes + `CHUNK_OF` edges (span-overlap
  linking; gap chunks link the File node).
- **`Embedder`** ABC + **`FakeEmbedder`** (deterministic, CI default) +
  **`BedrockEmbedder`** (Cohere `cohere.embed-v4:0`, 1024-dim, via boto3 in
  a `bedrock` extra; optional STS assume-role for CI).
- **`EmbedPipeline`** + **`CodeGraph.embed()`** + **`ckg embed`** /
  `ckg index --embed`. Coarse hash-skip incrementality (unchanged chunk set
  → no re-embed); per-file clean-replace of vectors.
- A vector hit expands into the graph via `CHUNK_OF` (`Store.expand`) — the
  feat-006 entry point.
- ~97% whole-package coverage with the fake embedder; the Bedrock path is an
  **env-gated live test** (`CKG_LIVE_BEDROCK=1`); `mypy --strict`, ruff.

**Decisions / deferrals** (design §8/§9): **Voyage is not on Bedrock** →
Cohere embed-v4 (memory `embeddings-bedrock`); chunk from symbol spans, not
a re-parse; embeddings opt-in (cost/creds); token budget via heuristic;
`DirtySet` incrementality and re-chunk cleanup of stale CHUNK nodes are
feat-004. Markdown/doc chunking is feat-010. CI gains AWS once the user
wires the assume-role ARN.
