# feat-010: ADR & docs ingestion

## Metadata

| Field | Value |
|---|---|
| **ID** | feat-010 |
| **Title** | ADR & docs ingestion (decisions and docs as first-class graph citizens) |
| **Status** | proposed |
| **Owner** | kjoshi |
| **Created** | 2026-06-11 |
| **Target version** | 0.3.0 |
| **Languages** | python |
| **Module package(s)** | `agentforge_graph.knowledge` |
| **Depends on** | feat-005, feat-006 |
| **Blocks** | none |

---

## 1. Why this feature

This is differentiator #1. The research's strongest finding (§3.3):
across 15+ surveyed tools, **none** connects architecture decision
records, design docs, READMEs, or commit messages to the code they
govern. ADR tooling (adr-tools, MADR, log4brains) and code graphs
exist in disjoint universes. The consequence is the most expensive
failure mode of coding agents: an agent refactors code in a way a
documented decision explicitly forbids, because the decision lived
in `docs/adr/0007-*.md` and the agent only retrieved `auth.py`.

## 2. Why it must ship in the agent core

- `Decision`/`DocChunk` nodes and `GOVERNS`/`DESCRIBES`/`SUPERSEDES`
  edges are schema (reserved in feat-001) — producing them
  consistently, with provenance separating parsed links (explicit
  paths in the ADR) from inferred ones (LLM-matched), is core
  discipline.
- Retrieval integration is the point: a `ckg_search` hit on
  `auth.py` must *automatically* surface the governing decision.
  That join lives in feat-006's expansion (one new edge-kind default)
  — only reachable if decisions are in the same graph.
- Doc chunking reuses feat-005's pipeline (markdown strategy) and
  feat-004's dirty tracking — docs are just another extractor.

## 3. How consumers benefit

- Refactoring agent touching `payments/` is told, in its first
  retrieval, "ADR-0012 (accepted, 2025-11): payment idempotency keys
  must be generated client-side — supersedes ADR-0007" — before it
  writes a line.
- "Why is it built this way?" gets a real answer: `ckg_decisions
  scope=src/app/auth/` returns the accepted decisions governing that
  subtree, with status and dates.
- Stale-doc detection for free: a `DESCRIBES` edge whose code side
  churned (feat-009) while the doc side didn't is a staleness
  signal, queryable.

## 4. Feature specifications

### 4.1 User-facing experience

```bash
ckg index   # now also ingests docs/adr/**, **/*.md, docstrings
```

```python
decisions = await graph.decisions(scope="src/app/payments/")
ctx = await graph.retrieve("refactor payment retry logic")
# ctx now contains Decision items when governing decisions exist
```

MCP tool `ckg_decisions(scope?, status?)` registers (reserved in
feat-008).

### 4.2 Public API / contract

**Node attrs:**

- `Decision`: `title`, `status`
  (`proposed|accepted|superseded|deprecated|rejected`), `date`,
  `path`, `body_chunks` (DocChunk ids). Parsed from MADR /
  adr-tools / Nygard formats (auto-detected) under configurable
  globs.
- `DocChunk`: markdown-aware chunks (heading-bounded, feat-005
  `Chunker` with a `MarkdownChunker` strategy), embedded into the
  same vector store with `source_type: doc` filterable metadata.

**Edges:**

| Edge | Produced by | Provenance |
|---|---|---|
| `GOVERNS` Decision→Package/File/Symbol | explicit path/symbol mentions parsed from ADR body | `parsed` |
| `GOVERNS` (inferred) | LLM matcher: decision text ↔ repo-map candidates | `llm`, confidence |
| `SUPERSEDES` Decision→Decision | ADR status/links section | `parsed` |
| `DESCRIBES` DocChunk→Symbol | path/qualified-name mentions in any doc; docstrings attach to their own symbol | `parsed` |

```python
class ADRExtractor(Extractor): ...        # feat-001 ABC, like any pack
class DocLinkInferencer(Enricher):        # the LLM matcher, optional
    async def enrich(self, graph) -> list[Edge]
```

### 4.3 Internal mechanics

- **Parse pass (deterministic):** glob → format detect → frontmatter/
  sections → `Decision` node + DocChunks. Mentions matched against
  the symbol/path index: backtick code spans, repo-relative paths,
  qualified names. Only unambiguous matches become `parsed` edges.
- **Infer pass (optional, budgeted):** for decisions with zero parsed
  `GOVERNS` edges, an AgentForge agent call matches decision text
  against feat-007's ranked symbols; writes `llm`-provenance edges
  with confidence; capped per run by AgentForge budget rails.
  Off by default; `ckg enrich --decisions` runs it.
- **Retrieval wiring:** `context` mode expansion follows
  `GOVERNS`/`DESCRIBES` one hop from any retrieved symbol by
  default; Decision items render with status and date prefix.
- Commit-message ingestion (cheap, high-value): messages matching
  conventional-commit or issue-ref patterns become DocChunks
  `DESCRIBES`-linked to the symbols their commit touched (span
  overlap via feat-009 data when present; file-level otherwise).

### 4.4 Module packaging

`agentforge_graph.knowledge` — default install; LLM inference uses
the AgentForge model configured for the project.

### 4.5 Configuration

```yaml
knowledge:
  adr_globs: ["docs/adr/**/*.md", "docs/decisions/**/*.md"]
  doc_globs: ["**/*.md"]
  commit_messages: true
  infer_governs: off         # LLM pass opt-in
  infer_budget_usd: 1.0
```

## 6. Cross-language parity

n/a.

## 7. Test strategy

- Golden: MADR / Nygard / adr-tools fixture files → expected
  Decision nodes, statuses, SUPERSEDES chains.
- Linking precision unit tests: backtick path, bare path, qualified
  name, ambiguous name (must NOT link).
- Integration: retrieval on a fixture repo returns the governing
  decision for a governed symbol; does not for an ungoverned one.
- LLM pass (env-gated live): inferred edges carry `llm` provenance
  and confidence; budget cap respected.

## 8. Risks & open questions

| Risk / Question | Mitigation / Decision |
|---|---|
| ADR formats in the wild are messy | Format detection is best-effort; unparseable files still become DocChunks (degrade, don't drop); parse-rate reported in IndexReport |
| Inferred GOVERNS edges pollute trust | Off by default, `llm` provenance, confidence threshold (≥0.7) for retrieval inclusion, `include_llm_facts=False` escape hatch (feat-006) |
| Repos with zero ADRs get nothing from the headline feature | Commit messages + READMEs + docstrings still light up DESCRIBES; and `ckg adr new` scaffold (post-0.3 idea) can seed the practice |
| Doc chunk volume diluting code search | `source_type` metadata filter; feat-006 modes weight code over docs unless query smells architectural |

## 9. Out of scope

- Issue tracker / PR ingestion (GitHub API) — post-1.0, same edge
  vocabulary.
- Authoring/managing ADRs (we read them; log4brains writes them).
- Stale-doc *reporting UI* (the signal is queryable; reporting is a
  consumer concern).

## 10. References

- Research §3.3 (the gap — verified absence across survey), §5
  items 11 & 14.
- MADR spec, adr-tools, log4brains (formats).
- feat-005 (chunker reuse), feat-006 (expansion wiring), feat-008
  (`ckg_decisions`), feat-009 (churn for staleness).

---

## Implementation status

**MVP shipped** (branch `feat/010-adr-and-docs-ingestion`). New package
`agentforge_graph.knowledge` (zero `agentforge` imports): `ADRParser`
(MADR frontmatter + Nygard/adr-tools sections, status/date/supersedes, filename
fallback), precise mention extraction/resolution (`mentions.py` — paths +
qualified names, **unambiguous-only**; ambiguous counted), and
`KnowledgeIngestor` → `Decision` nodes (+ body `DocChunk`s) with parsed
`GOVERNS`/`SUPERSEDES` edges.

Each ADR is upserted as its own `FileSubgraph` (origin_path = ADR path), so
edits/deletes ride feat-004 incrementality with no `ChangeDetector` change; the
pass runs after code indexing (mention indices see current code) and GCs
decisions whose ADR file vanished. `SUPERSEDES` uses a two-round upsert so the
target decision exists.

**Retrieval surfacing** (the differentiator): `GOVERNS`/`DESCRIBES` added to the
default `context` expansion, and a retrieved `Decision` renders with a
`[status, date]` prefix — so a `ckg_search`/`ckg_symbol` hit on a governed
symbol surfaces its decision. Surfaces: `CodeGraph.decisions(scope, status)`,
`ckg decisions` CLI, `ckg_decisions` MCP tool (now in `ALL_TOOLS` — 8 tools),
`knowledge:` config. `IndexReport` + `decisions_indexed`/`governs_resolved`/
`mentions_unresolved`. ≥97% package coverage; `mypy --strict` + ruff clean.
Design: `docs/design/design-010-adr-and-docs-ingestion.md`.

### Follow-ups
- **Embed `DocChunk`s ✅ done** (2026-06-18, `feat/010-embed-doc-chunks`): the embed
  pass now embeds ADR `DocChunk` prose into the vector store with a `source_type:
  doc` tag (code chunks tagged `source_type: code`), clean-replacing by the
  `DocChunk` kind each run (also GCs vectors for removed ADRs). A doc-chunk vector
  hit surfaces the chunk **and** seeds its containing `Decision` (via `CONTAINS`),
  which expands through `GOVERNS` to the governed code — so an architectural query
  reaches the decision and the code it governs. `EmbedReport.doc_chunks` counts
  them. Residual: doc-incremental-by-hash (the chunk `content_hash` is now stored
  for it) and `source_type`-aware code-over-doc retrieval weighting.
- **LLM `infer_governs` pass ✅ done** (2026-06-18, `feat/010-infer-governs`): an
  optional matcher (`DecisionGovernsInferencer` + injectable `GovernsMatcher` —
  `ScriptedMatcher` for tests, `ClaudeGovernsMatcher` over Bedrock/Anthropic via
  `enrich.provider`) proposes `GOVERNS` edges for decisions with **zero parsed**
  links, matching the decision's prose against the repo's candidate symbols under
  a `BudgetPolicy` cap. Matches above the confidence floor become `GOVERNS` edges
  with honest `llm` provenance + confidence + rationale. Never overrides a parsed
  link (only zero-parsed decisions are considered); re-run is idempotent. Off by
  default — `ckg enrich --decisions` / `CodeGraph.infer_governs`. Residual:
  repo-map-ranked candidate selection (currently id-sorted, capped at 60).
- **Docstrings → `DESCRIBES` ✅ done (Python)** (2026-06-18, `feat/010-docstrings`):
  a Python symbol's leading docstring (the first body string of a class/function/
  method) becomes a `DocChunk` that `DESCRIBES` the symbol — embedded with the
  doc-chunk pass (`source_type: doc`) and, on a vector hit, seeding the symbol it
  describes so a docstring-prose query reaches the code. Carried in the file's
  subgraph (origin_path = code file) so it rides feat-004 incrementality; symbols
  without a leading docstring get nothing. Residual: JS/TS JSDoc, Java/C# doc
  comments, module-level docstrings → File.
- General `doc_globs` (README/`**/*.md` → DocChunks + DESCRIBES); commit-message
  ingestion; doc-incremental-by-hash.
