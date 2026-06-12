# Design Doc: feat-005 AST chunking & embeddings

> Per-feature design doc (design stage). Mirrors
> `docs/features/feat-005-ast-chunking-and-embeddings.md`. The spec says
> *what & why*; this doc says *how* — file layout, exact types, resolved
> decisions, test plan, chunk plan.

---

## Metadata

| Field | Value |
|---|---|
| **Title** | feat-005 AST chunking & embeddings |
| **Status** | accepted |
| **Owner** | kjoshi |
| **Created** | 2026-06-12 |
| **Last updated** | 2026-06-12 |
| **Related features** | feat-005 (this) · consumes feat-002, feat-003 · consumed by feat-006, feat-010 |
| **Related ADRs** | ADR-0001 (layering), ADR-0006 (embedded storage), ADR-0007 (AST chunking), ADR-0008 (hybrid retrieval) |

---

## 1. Context

Vector search is how an agent *enters* the graph (NL question → code
region); chunk quality caps retrieval quality. feat-005 turns the indexed
code symbols into embedded, retrievable **chunks** linked back to their
symbols (`CHUNK_OF`), so a vector hit can expand into the graph (feat-006).

Two product decisions are settled (and shape this design):

- **Chunk scope: code symbols only.** Markdown/ADR/doc chunking is feat-010.
- **Embeddings: Cohere `cohere.embed-v4:0` on AWS Bedrock** (verified
  invocable from the configured AWS CLI; **Voyage is not on Bedrock**). CI
  has no AWS creds yet, so tests default to a **deterministic fake
  embedder**, with the Bedrock embedder as an **env-gated live test**; the
  user will add a CI assume-role ARN later, which the embedder already
  supports. See memory `embeddings-bedrock`.

## 2. Goals

- `agentforge_graph.chunking` + `agentforge_graph.embed` packages, **zero
  `agentforge` imports** (ADR-0001) — boto3 is fine (it's not the framework).
- A `Chunker` ABC + `CASTChunker` that never splits a symbol that fits the
  budget and never fuses two unrelated top-level defs; full line coverage.
- `Chunk` → `NodeKind.CHUNK` nodes with `CHUNK_OF` edges to the symbols they
  cover; chunk text embedded into the feat-003 `VectorStore`.
- An `Embedder` ABC with `FakeEmbedder` (deterministic, CI default) and
  `BedrockEmbedder` (Cohere embed-v4 via boto3, optional STS assume-role).
- An `EmbedPipeline` + `CodeGraph.embed()` + `ckg embed` CLI.
- ≥90% coverage with the fake embedder (real Bedrock path covered by a
  live test); `mypy --strict`; ruff.

## 3. Non-goals

- Non-code chunking (markdown/ADRs/commits) — feat-010 reuses `Chunker`.
- Reranking / query-time graph expansion — feat-006.
- True incrementality (`DirtySet`) — feat-004. We do **coarse hash-skip**
  (unchanged chunk `content_hash` → skip re-embed); `scope="all"` for now.
- The other nine languages (ride feat-002's packs as they land).
- A real tokenizer — chunk budgeting uses a consistent heuristic (§4.3).

## 4. Proposal

### 4.1 Package layout

```
src/agentforge_graph/chunking/
  __init__.py     # Chunk, Chunker, CASTChunker
  chunk.py        # Chunk value model
  cast.py         # CASTChunker (split-then-merge over symbol spans)
  tokens.py       # estimate_tokens (heuristic; consistency over exactness)
src/agentforge_graph/embed/
  __init__.py     # Embedder, FakeEmbedder, BedrockEmbedder, EmbedPipeline,
                  #   EmbedReport, embedder_from_config
  base.py         # Embedder ABC
  fake.py         # FakeEmbedder (deterministic hash embedding)
  bedrock.py      # BedrockEmbedder (Cohere embed-v4 via boto3 + optional STS)
  pipeline.py     # EmbedPipeline.run -> EmbedReport
  registry.py     # driver name -> Embedder factory
  report.py       # EmbedReport
tests/chunking/   tests/embed/   (+ fixtures reused from tests/ingest)
```

Layering tests assert neither package imports `agentforge*`.

### 4.2 `Chunk` + linking (`chunk.py`)

```python
class Chunk(BaseModel):
    id: str                 # SymbolID: descriptor "chunk(<seq>)." on the file path
    text: str               # the embedding text (see §4.3 prefix)
    code: str               # raw source slice (for display)
    token_count: int
    path: str
    span: tuple[int, int]   # 1-based line range, covers a contiguous block
    content_hash: str       # sha256(text + chunker-params + model) — the vector key
    symbol_ids: list[str]   # CHUNK_OF targets (symbols whose def-start ∈ span); File if none
    seq: int                # order within the file
```

- A chunk becomes a `Node(kind=CHUNK, …, attrs={path, span, token_count,
  content_hash, seq})` plus one `CHUNK_OF` edge per `symbol_ids` entry
  (`src=chunk, dst=symbol`). Chunks with no symbol start in range link to the
  File node, so every chunk has ≥1 `CHUNK_OF`.
- Chunk id is stable per `(path, seq)` so re-chunking updates in place; the
  **vector** is keyed by `content_hash`, so unchanged text skips re-embed.

### 4.3 `CASTChunker` (`cast.py`) — split-then-merge over symbol spans

cAST without a re-parse: the extractor already produced symbol spans, and
top-level symbols *are* the meaningful AST nodes for code. The chunker
partitions the file's lines into contiguous chunks honoring those
boundaries (a deliberate simplification of "walk the full AST" — logged in
§9; falls back to line windows where a unit lacks symbol structure).

`chunk(file: SourceFile, symbols: list[Node]) -> list[Chunk]`:

1. Derive **top-level** symbols = those whose span isn't strictly contained
   in another symbol's span (from spans alone — no edges needed).
2. Walk the file as an ordered sequence of *units*: each top-level symbol
   span, and the inter-symbol **gaps** (imports, module code, blanks).
3. For each unit:
   - symbol that fits (`≤ max_tokens`) → one chunk;
   - oversized symbol → split into its nested children (a 900-token class →
     per-method chunks, each prefixed with the class signature line for
     context); a leaf function still too big → line windows ≤ `max_tokens`
     (logged, never silent);
   - gap → line windows ≤ `max_tokens`.
4. Greedily **merge** adjacent *small* units (< `min_tokens`: gaps,
   one-liners) up to `max_tokens`, **never across a top-level symbol**.
5. Link each chunk via span-intersection: `CHUNK_OF` to every symbol whose
   **def-start line** falls inside the chunk (so a fitting class chunk links
   the class *and* its methods); gap chunks link the File node.

Properties guaranteed (the §7 tests): every non-blank line covered exactly
once; no chunk exceeds `max_tokens` unless it is a single atomic line; a
symbol that fits is never split and never fused with another.

**Token budget** (`tokens.py`): `estimate_tokens` is a fast heuristic
(≈ `len(text)/4`, floored to word count) — exactness doesn't matter, only
consistency between budgeting and the boundary tests. A real tokenizer is a
later swap (ADR-0007 risk).

**Embedding text format**: `"<path> | <qualified symbol>\n<code>"` — the
path/symbol prefix measurably helps code retrieval for a few tokens.

### 4.4 `Embedder` (`base.py`, `fake.py`, `bedrock.py`)

```python
class Embedder(ABC):
    name: str
    dim: int
    @abstractmethod
    async def embed(self, texts: list[str],
                    input_type: Literal["document","query"] = "document") -> list[list[float]]: ...
```

- **`FakeEmbedder(dim=256)`** — deterministic: seed a hash of each text,
  emit `dim` floats, L2-normalized. No creds, no network → the CI default.
  Stable vectors make retrieval tests reproducible.
- **`BedrockEmbedder`** — Cohere `cohere.embed-v4:0` via
  `boto3.client("bedrock-runtime")`:
  - body `{"texts": batch, "input_type": "search_document"|"search_query",
    "embedding_types": ["float"], "output_dimension": dim}`; response
    `embeddings.float[]`. `dim` default **1024**, `batch_size` ≤ 96.
  - **Optional `assume_role_arn`**: if set, STS-assume it for a session
    (the CI path); else the default credential chain (local AWS CLI). Region
    from config (`us-east-1`).
  - Retries on throttling with backoff; raises clearly on `AccessDenied`.
  - boto3 is imported lazily inside `bedrock.py` and declared in a `bedrock`
    extra, so the base install and the fake path don't need it.

`embedder_from_config(EmbedConfig)` (`registry.py`) maps `driver` →
`fake`/`bedrock` (voyage/fastembed are later additions).

### 4.5 `EmbedPipeline` (`pipeline.py`)

```python
class EmbedReport(BaseModel):
    files: int; chunks: int; embedded: int; skipped_unchanged: int
    model: str; dim: int

class EmbedPipeline:
    def __init__(self, chunker: Chunker, embedder: Embedder): ...
    async def run(self, store: Store, source: RepoSource,
                  registry: PackRegistry) -> EmbedReport: ...
```

Per file from `source.iter_files`: fetch its symbol nodes from the graph
(`GraphQuery(path_prefix=path)`), `chunk(file, symbols)`, then for chunks
whose `content_hash` isn't already a vector (`vectors.search`-free hash skip
via a stored set / `delete_where(path)` + re-add), embed in batches and:
- `store.graph.add([chunk_nodes…, chunk_of_edges…])` (Chunk nodes + edges),
- `store.vectors.upsert([Embedded(ref=chunk.id, vector, kind=CHUNK,
  attrs={path, span, symbol_ids, model})])`.

Coarse incrementality at 0.1: `delete_where({"path": path})` then re-embed
the file's chunks (clean replace); feat-004 will scope to a `DirtySet`.
Vectors carry the model name in attrs; a model change ⇒ rebuild (spec §5).

### 4.6 `CodeGraph.embed()` + CLI

- `CodeGraph.embed(embedder=None)` — chunk+embed everything indexed; builds
  the embedder from `EmbedConfig` if not passed. Returns `EmbedReport`,
  exposed via `stats()`-style accessor.
- `CodeGraph.index(..., embed=False)` — opt-in to embed right after indexing
  (reuses the open store). Default off (embedding costs money / needs creds).
- CLI: **`ckg embed [PATH] [--config]`** runs `CodeGraph.open` + `embed`;
  `ckg index --embed` does both. Report printed (files, chunks, embedded,
  skipped, model, dim).

### 4.7 Configuration (`config.py`)

Add two `_Block`s:

```yaml
chunking:
  max_tokens: 512
  min_tokens: 64
embed:
  driver: bedrock          # bedrock | fake  (fastembed/voyage later)
  model: cohere.embed-v4:0
  region: us-east-1
  dim: 1024
  batch_size: 96
  assume_role_arn: ""      # set for CI; empty = default AWS cred chain
```

Tests pass `driver: fake` (or construct `FakeEmbedder` directly) so CI never
needs AWS.

### 4.8 Dependencies / CI

- `boto3` in a new `bedrock` extra. CI keeps running `--extra dev --extra
  engine` (fake embedder path), so **no AWS in CI yet**; when the user adds
  the assume-role ARN + OIDC, a CI step can opt the live test in via env.

## 5. Alternatives considered

| Option | Why not |
|---|---|
| Re-parse files in the chunker (full AST walk) | Duplicates feat-002's parse and re-couples chunking to tree-sitter; symbol spans already capture the AST structure we need for code. |
| Default to fastembed (local) | User chose Bedrock Cohere v4; fake covers CI. fastembed stays a future driver. |
| Voyage via Bedrock | Not offered on Bedrock (verified). Voyage-native would need a non-AWS key; out of scope. |
| Conflate chunks with symbol nodes | Breaks the chunk↔symbol separation (cognee insight) that lets a vector hit expand into the graph (feat-006). |
| Real tokenizer now | Adds a dep for budgeting precision that doesn't affect correctness; heuristic is consistent. |
| Embed inside the ingest extract loop | Couples costly/credentialed embedding to indexing; keep `EmbedPipeline` separate so `embed()` re-runs on model change. |

## 6. Migration / rollout

Greenfield. Chunk nodes/edges and vectors are derivable — rebuild on chunker
or model change (params + model hashed into `content_hash` / vector attrs).
`ckg embed` is re-runnable and idempotent (hash-skip + per-file replace).

## 7. Risks

| Risk | Mitigation |
|---|---|
| No AWS in CI yet | Fake embedder is the CI default; Bedrock path is an env-gated live test; embedder supports the assume-role ARN for when CI is wired. |
| Chunk boundary quality vs real cAST | Symbol-span partitioning meets the property tests; chunker is an ABC, swappable; a retrieval smoke test (env-gated) gives a behavioral metric. |
| Token heuristic vs model tokenizer | Budgeting only; consistent estimate; real tokenizer is a drop-in later. |
| Cohere v4 request/response shape drift | Pinned model id; one adapter; live test catches drift; clear error on AccessDenied/throttle. |
| Oversized leaf functions | Line-window fallback, logged in the report, never silent. |
| boto3 weight | Isolated in the `bedrock` extra + lazy import; base/fake path unaffected. |

## 8. Open questions (decisions for review)

1. **Embed during `index` or only via `ckg embed`?** Proposed: **both** —
   `ckg embed` is primary; `ckg index --embed` is a convenience. Default
   index does *not* embed (cost/creds).
2. **Default output dim for Cohere v4?** Proposed: **1024** (balance of
   quality vs index size; v4 supports 256–1536).
3. **Chunker scope simplification** (symbol spans, not a full re-parse AST
   walk)? Proposed: **yes** for v0.1 — meets the property tests without a
   second parse; full-AST refinement is a later swap behind the same ABC.

## 9. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-12 | Embeddings = Cohere embed-v4 on Bedrock; fake embedder for CI | Voyage not on Bedrock; CI lacks AWS creds (assume-role ARN pending) |
| 2026-06-12 | Chunk from extracted symbol spans, not a re-parse | Avoids a second parse; spans are the AST structure code chunking needs |
| 2026-06-12 | Chunk node id stable per (path, seq); vector keyed by content_hash | In-place re-chunk; unchanged text skips re-embed (coarse incrementality) |
| 2026-06-12 | `EmbedPipeline` separate from ingest; `ckg embed` + `index --embed` | Decouples costly/credentialed embedding; re-runnable on model change |
| 2026-06-12 | boto3 in a `bedrock` extra, lazy import; embedder supports STS assume-role | Keeps base/fake path dep-free; ready for the CI role ARN |
| 2026-06-12 | Token budget via heuristic, not a tokenizer | Consistency over exactness; real tokenizer is a later swap |

## 10. Chunk plan (the single feat-005 PR)

| Chunk | Commit | Contents |
|---|---|---|
| 0 | `chore(005): chunking/embed config + bedrock extra` | `ChunkingConfig`/`EmbedConfig` in config.py; `boto3` `bedrock` extra; design accepted |
| 1 | `feat(005): cAST chunker` | `chunking/` (Chunk, tokens, CASTChunker); property + golden boundary tests |
| 2 | `feat(005): embedder abc + fake` | `embed/base.py`, `embed/fake.py`, registry; deterministic embedding tests |
| 3 | `feat(005): bedrock cohere embedder` | `embed/bedrock.py` (boto3, optional STS assume-role); env-gated live test |
| 4 | `feat(005): embed pipeline + CodeGraph.embed` | `embed/pipeline.py`, Chunk nodes + CHUNK_OF + vector upsert, hash-skip; `CodeGraph.embed`/`index --embed` |
| 5 | `feat(005): ckg embed CLI` | `ckg embed` command + `index --embed` flag |
| 6 | `test(005): end-to-end + layering` | fake-embedder end-to-end (chunks+edges+vectors queryable), layering, retrieval-shape smoke |
| 7 | `docs(005): impl status + tracker; design accepted` | spec status; TRACKER; this doc → accepted |

## 11. References

- Spec: `docs/features/feat-005-ast-chunking-and-embeddings.md`
- ADRs: 0001 (layering), 0006 (embedded storage), 0007 (AST chunking),
  0008 (hybrid retrieval)
- feat-002 (`FileSubgraph`/symbol spans, `RepoSource`, `PackRegistry`),
  feat-003 (`Store`/`VectorStore`/`Embedded`/`ScoredRef`), feat-006 (consumer)
- Memory: `embeddings-bedrock` (model/account/CI decision)
- cAST paper: arxiv.org/abs/2506.15655
