# Design Doc: feat-012 (cont.) — bottom-up summaries

> Per-feature design doc (design stage), the **summaries** half of feat-012.
> Builds directly on `design-012-llm-enrichment.md` (pattern tagging, shipped):
> same `enrich` package, same injectable-judge pattern, same budget/dirty/
> `clear_outgoing` rails, same Bedrock Claude judge plumbing.

---

## Metadata

| Field | Value |
|---|---|
| **Title** | feat-012 bottom-up module summaries (MVP) |
| **Status** | accepted |
| **Owner** | kjoshi |
| **Created** | 2026-06-13 |
| **Last updated** | 2026-06-13 |
| **Related features** | feat-012 (this, cont.) · consumes feat-005 (embed) / feat-006 (retrieval) / feat-007 (repo map) · completes feat-008's `ckg_explain` |
| **Related ADRs** | ADR-0001 (layering), ADR-0004 (provenance), ADR-0005 (locked kinds) |

---

## 1. Context

Pattern tags shipped; this adds the other half of feat-012 — **prose summaries**
that turn the symbol dump into a guided tour. The win is concrete: feat-007's
repo map gains a one-line `[llm]` summary per file; `ckg_search` can land on a
*concept* ("payment retry logic") via an embedded summary and expand to the
code (the GraphRAG move); `ckg_explain` finally returns prose. `Summary` nodes
and `SUMMARIZES` edges are reserved; the harness (heuristics→judge→budget→dirty→
`clear_outgoing`) is already built — summaries swap the "judge" for a
"summarizer" and add embedding.

## 2. Goals

- A **`SummaryEnricher`** in `agentforge_graph.enrich`, bottom-up over
  `CONTAINS`: **file** summaries from a file's symbols (signatures + docstrings),
  then **one repo** summary synthesized from the file summaries (2-tier
  bottom-up; per-package/per-symbol deferred — spec allows file-only).
- An **injectable `Summarizer`** (mirrors `PatternJudge`): `BedrockClaudeSummarizer`
  (the live adapter, reusing the feat-012 Bedrock plumbing) and a
  `ScriptedSummarizer` so the whole enricher is deterministic in CI.
- `Summary` nodes — `attrs={text (≤max_words), level (file|repo), model,
  prompt_version}` — `SUMMARIZES` → the file (or a synthesized `Repository`
  node). `source="llm"` + confidence + `clear_outgoing`-idempotent re-summarize.
- **Embedded** into the vector store with `attrs.source_type="summary"`, so a NL
  query can hit a summary and expand to its code via `SUMMARIZES`.
- Budgeted (`BudgetPolicy`), resumable via `DirtySet("summaries")`.
- **Surfaces:** `Summary` rendered in retrieval (`[summary]` + `SUMMARIZES` in
  context expansion); a one-line file summary in the **repo map**; `ckg_explain`
  gains the owning-file summary; `ckg enrich --summaries` (+ `--all`);
  `CodeGraph.summarize()`.
- ≥90% coverage (deterministic core via `ScriptedSummarizer`); `mypy --strict`;
  ruff.

## 3. Non-goals (follow-ups)

- **Per-package (directory) and per-symbol** summaries — needs directory nodes /
  is the most expensive tier; file + repo is the spec's "file-only is fine" MVP.
- Staleness *rendering* (a `SUMMARIZES` whose code churned) — the signal is
  feat-009; queryable later.
- Summary *quality* tuning / prompt iteration beyond a sane default.

## 4. Proposal

### 4.1 Package additions

```
src/agentforge_graph/enrich/
  summarizer.py      # Summarizer Protocol + Summary value + ScriptedSummarizer
  bedrock_summarizer.py   # BedrockClaudeSummarizer (reuses bedrock.py client plumbing)
  summary_enricher.py     # SummaryEnricher: bottom-up file→repo, embed, budget, dirty
src/agentforge_graph/
  enrich/report.py        # + SummaryReport, SummaryInfo
  config.py               # EnrichConfig += summary_max_words, summary_levels
  ingest/codegraph.py     # + summarize(); enrich(summaries=…/patterns=…); summaries()
  retrieve/retriever.py   # SUMMARIZES in context expansion; entry seeds SUMMARIZES; render Summary
  repomap/{repomap,render}.py  # inject a file's summary line (when present)
  serve/engine.py         # explain() gains the owning-file summary
  cli.py                  # `ckg enrich --summaries|--patterns|--all`
tests/enrich/             # summarizer(scripted) + bottom-up order + embed + repomap + live(gated)
```

### 4.2 Bottom-up generation (`summary_enricher.py`)

1. **Candidate files:** `DirtySet("summaries")` if non-empty, else all `FILE`
   nodes (cold).
2. **File summaries (leaf tier):** for each file, gather its symbols
   (`CONTAINS` children) — names, `attrs["signature"]`, and any docstring the
   extractor captured — plus the file's top imports; hand to
   `Summarizer.summarize_file(file_ctx)` → a `Summary` (≤ `summary_max_words`).
   Emit a `Summary` node (`level="file"`) + `SUMMARIZES` → the file node.
3. **Repo summary (root tier, bottom-up):** synthesize one repo `Summary` from
   the *file summaries just produced* (bounded prompt — the file one-liners, not
   the whole tree). Target a synthesized `Repository` node
   (`SymbolID.for_symbol("repo", repo, "<repo>", "repository.")`, created once).
4. **Embed:** embed each summary's text (the configured embedder — Bedrock
   Cohere) and `vectors.upsert(Embedded(ref=summary_id, kind=SUMMARY,
   attrs={path, source_type:"summary"}))`.
5. **Budget/idempotency/dirty:** same as pattern tagging — `BudgetPolicy` cap
   (stop → partial persisted, rest stay dirty); `clear_outgoing(file_ids,
   SUMMARIZES)` + `vectors.delete_where({"ref": …})` before re-adding;
   `mark_clean("summaries", done)`.

`Provenance.llm("summaries@<v>", confidence=1.0, commit)` (summaries don't carry
a meaningful per-item confidence; honesty is the `llm` source + model +
prompt_version in attrs).

### 4.3 Injectable summarizer

```python
class Summary(BaseModel):
    text: str
    model: str = ""

class Summarizer(Protocol):
    async def summarize_file(self, ctx: FileContext) -> Summary: ...
    async def summarize_repo(self, file_summaries: list[str]) -> Summary: ...
    @property
    def cost_usd(self) -> float: ...
```

`ScriptedSummarizer` returns a canned/derived string (e.g. `"summary of
<file>"`), `cost_usd=0` — the enricher, bottom-up order, embedding, budget, and
idempotency are all tested without a model. `BedrockClaudeSummarizer` reuses
`bedrock.py`'s client/cost helpers (factor the boto3 client + price table into a
shared `_BedrockClient`), one `invoke_model` per summary, plain-text output
(no tool needed), cost from usage.

### 4.4 Retrieval, repo map, explain

- **Retriever:** add `SUMMARIZES` to `context` expansion; a summary vector hit
  seeds its `SUMMARIZES` target (so "payment retry logic" → summary → the code);
  render a `Summary` item as `[summary] <text>`. `llm` provenance →
  `include_llm_facts=False` excludes (unchanged).
- **Repo map:** under each file header, if the file has a `Summary`, emit one
  indented `# <summary>` line before its symbols (budget-counted like any line;
  dropped first if space is tight). A new `RepoMap` query for file summaries;
  `render_map` gains an optional `summaries: dict[path, str]`.
- **`ckg_explain` / engine.explain():** add the owning file's summary text to
  the existing tags+facts envelope.

### 4.5 Config & CLI

- `EnrichConfig += summary_max_words: int = 120`, `summary_levels: list[str] =
  ["file", "repo"]`.
- `ckg enrich [--patterns] [--summaries] [--all] [--budget-usd N]` — default
  (no flag) runs **patterns** (today's behavior preserved); `--summaries` runs
  summaries; `--all` both. `CodeGraph.enrich(patterns=False, summaries=False)`
  gains the flags; `CodeGraph.summarize()` is the explicit entry.

## 5. Alternatives considered

| Option | Why not |
|---|---|
| Per-symbol/per-package summaries in the MVP | Per-symbol is the most expensive tier; per-package needs directory nodes. File+repo delivers the repo-map/search win at a fraction of the cost (spec: file-only is fine). |
| Don't embed summaries | Then a concept query can't *land* on a summary — the GraphRAG move is the headline. Embedding is cheap (one vector per file). |
| Reuse `EmbedPipeline` for summary embedding | It's chunk/code-oriented; embedding a handful of summary strings directly is simpler and avoids coupling. |
| A second LLM-judge-style confidence per summary | Summaries aren't accept/reject; honesty is `llm` provenance + model + prompt_version, and the opt-out. |
| Whole-file-tree prompt for the repo summary | Unbounded context/cost; bottom-up from the file one-liners is the point. |

## 6. Migration / rollout

Additive: new modules, `EnrichConfig` fields, kinds reserved (no schema bump).
Never implicit — `ckg enrich --summaries` only. `ckg enrich` with no flag stays
patterns-only (no behavior change). Embedding summaries reuses the configured
embedder; a repo with no enrich run shows no summaries (repo map / explain
unchanged). Re-summarize is idempotent (clear + re-embed by ref).

## 7. Risks

| Risk | Mitigation |
|---|---|
| Summary drift vs code | `DirtySet("summaries")` re-summarizes changed files; staleness flag is feat-009 (later). |
| Cost on large repos | One call per file + one repo call; `budget_usd` breaker; `summary_levels` configurable (file-only); resumable. |
| Hallucinated prose | `llm` provenance + `[summary]`/`[llm]` markers + `include_llm_facts=False`; prompt says "summarize only what the signatures/docstrings show". |
| Doc-vector dilution of code search | `source_type:"summary"` filterable; summaries are few (one/file) vs many chunks. |

## 8. Open questions (decisions for review)

1. **Scope to file + repo summaries** (defer per-package/per-symbol)? Proposed: **yes**.
2. **Embed summaries** (`source_type:"summary"`) for concept→code search? Proposed: **yes**.
3. **Injectable `Summarizer`** (`ScriptedSummarizer` for CI, Bedrock live, reuse feat-012 plumbing)? Proposed: **yes**.
4. **Repo-map one-line file summary + `ckg_explain` prose + `SUMMARIZES` in context**? Proposed: **yes**.
5. **`ckg enrich --patterns|--summaries|--all`, default = patterns (no behavior change)**? Proposed: **yes**.

## 9. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-13 | Summaries reuse the feat-012 harness (judge→summarizer); 2-tier file+repo | Lowest-risk completion; spec allows file-only; demonstrates bottom-up |
| 2026-06-13 | Embed summaries (`source_type:"summary"`) | The GraphRAG concept→code move; cheap (one vector/file) |
| 2026-06-13 | Injectable `Summarizer` + `ScriptedSummarizer` | Deterministic CI, no model; Bedrock plumbing factored from feat-012 |
| 2026-06-13 | `ckg enrich` default stays patterns; `--summaries`/`--all` opt in | No behavior change for the shipped command |
| 2026-06-13 | **Implemented** idempotency by MERGE-node + create-edge-if-missing (no clear/recreate) | Hit a Kuzu bug: a forward `->` rel scan goes stale after delete+recreate on the same connection; `CHECKPOINT` fixes it but hard-crashes from the app connection. The `SUMMARIZES` edge target is stable, so never deleting it sidesteps the bug. Logged in docs/framework. |
| 2026-06-13 | Live summarizer on **Bedrock Claude** (shared `BedrockClient`), not the Anthropic API | Same call as feat-012 tagging (AWS creds); live-verified — grounded file + bottom-up repo summaries, ~$0.0016 for 2 calls |

## 10. Chunk plan (the single PR)

| Chunk | Commit | Contents |
|---|---|---|
| 0 | `chore(012): EnrichConfig summary fields; Summarizer skeleton; design accepted` | config; `summarizer.py` (Protocol + Summary + ScriptedSummarizer); this doc → accepted |
| 1 | `feat(012): SummaryEnricher — bottom-up file→repo + embed` | `summary_enricher.py`; SummaryReport; enricher with ScriptedSummarizer; bottom-up order + idempotency + embed tests |
| 2 | `feat(012): BedrockClaudeSummarizer (shared bedrock client)` | factor `_BedrockClient` from `bedrock.py`; `bedrock_summarizer.py`; live test (gated) |
| 3 | `feat(012): CodeGraph.summarize + enrich flags + ckg enrich --summaries/--all` | facade + CLI; DirtySet("summaries"); summaries() |
| 4 | `feat(012): retrieval (SUMMARIZES) + repo-map line + ckg_explain prose` | retriever entry/expansion/render; repomap inject; engine.explain summary; integration test |
| 5 | `docs(012): summaries shipped — spec status + tracker; design accepted` | spec; TRACKER; this doc accepted |

## 11. References

- `design-012-llm-enrichment.md` (the shipped pattern-tagging half — harness,
  judge pattern, budget/dirty/`clear_outgoing`, Bedrock plumbing)
- Spec: `docs/features/feat-012-llm-enrichment.md`
- feat-005 (embed), feat-006 (retrieval + `include_llm_facts`), feat-007 (repo
  map), feat-008 (`ckg_explain`); GraphRAG community-summary prior art
