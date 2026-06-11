# ADR-0008: Hybrid retrieval — vector entry, graph expansion, deterministic path

## Metadata

| Field | Value |
|---|---|
| **Number** | 0008 |
| **Title** | Hybrid retrieval (vector entry → graph expansion), no LLM in the retrieval path |
| **Status** | Accepted |
| **Date** | 2026-06-11 |
| **Deciders** | kjoshi |
| **Tags** | architecture, retrieval |

---

## 1. Context and problem statement

An agent asks two kinds of question: "where is the code that does X"
(semantic, suits vector search) and "what calls this / what breaks if I
change it / show the handler and its model" (structural, suits graph
traversal). Pure vector search can't answer the structural questions;
pure graph traversal needs a starting node the user doesn't have. The
tools that serve agents well (Potpie, cognee) combine the two. A
secondary question: should the retrieval path itself call an LLM (query
rewriting, HyDE), or stay deterministic? How do we shape the single
retrieval surface that every agent tool and enricher uses?

## 2. Decision drivers

- Agents need *connected context* (chunks + their symbols + 1-hop
  neighborhood), not disjoint snippets to stitch themselves.
- Reliability ranking must be uniform — resolved edges over heuristic,
  LLM facts visibly second-class (ADR-0004).
- The retrieval path is called constantly (it backs every MCP tool);
  it must be fast, cheap, and reproducible.
- "Impact" questions (reverse dependencies) are high-frequency and
  graph cannot be optional.

## 3. Considered options

1. **Pure vector retrieval** — embed everything, return top-k chunks.
2. **Pure graph retrieval** — traverse from a known symbol.
3. **Hybrid, deterministic** — vector entry → typed graph expansion →
   dedupe/rerank, with no LLM call in the path (LLM-derived *nodes*
   may be returned, flagged).
4. **Hybrid + LLM in path** — add query rewriting / HyDE inside
   retrieval.

## 4. Decision outcome

**Chosen: Option 3 — hybrid, deterministic.** `Retriever.retrieve`
takes a NL `query` and/or a `symbol`, enters via vector search
(chunks → owning symbols via `CHUNK_OF`) and/or direct node lookup,
expands through typed edges with mode-specific defaults (`context`,
`impact`, `definition`, `similar`), then dedupes by symbol ID and
optionally reranks with the AgentForge reranker. Scores decay per hop
and weight `resolved` above `parsed` provenance. The path makes no LLM
calls — it stays fast and reproducible — though it may *return* LLM
nodes (summaries, tags) flagged `[llm]` and filterable via
`include_llm_facts`.

### Positive consequences

- One call returns a connected context pack with `why` traces.
- `impact` mode answers reverse-dependency questions grep cannot.
- Deterministic, cacheable, testable against a fixed eval set; no
  per-query model cost.

### Negative consequences (trade-offs)

- Score fusion (vector × graph decay) is heuristic; exposed in config
  and arbitrated by an eval set, with optional rerank correcting
  finalists.
- No built-in query rewriting; agents that want it do it themselves
  (revisit only with eval evidence).
- Hub-node expansion can explode; capped per-hop with a no-silent-
  truncation note.

## 5. Pros and cons of the options

### Option A: Pure vector
- + Simple; good for "where is X".
- − Cannot answer structural/impact questions; returns disjoint
  snippets.

### Option B: Pure graph
- + Precise structural traversal.
- − Needs a seed node the NL user lacks; no semantic entry.

### Option C: Hybrid deterministic
- + Best of both; fast, cheap, reproducible; uniform ranking.
- − Heuristic score fusion to tune.

### Option D: Hybrid + LLM in path
- + Potentially better recall via query expansion.
- − Per-query cost and latency; nondeterministic; harder to test;
  premature without evidence.

## 6. References

- feat-006 (Retriever, modes, ranking), feat-005 (entry), feat-008
  (wraps it as tools), feat-007 (queryless sibling).
- agentforge-py feat-021/022/023 (reranker, hybrid search, graphrag).
- Research §3.1, §2.8 (Potpie), §2.6 (cognee).
- Related: ADR-0004, ADR-0007.
