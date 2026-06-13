# Design Doc: feat-010 ADR & docs ingestion (decisions in the graph, MVP)

> Per-feature design doc (design stage). Mirrors
> `docs/features/feat-010-adr-and-docs-ingestion.md`. The spec says *what & why*;
> this doc says *how*, and **scopes the first PR** to the deterministic core.

---

## Metadata

| Field | Value |
|---|---|
| **Title** | feat-010 ADR ingestion → Decision nodes + GOVERNS (MVP) |
| **Status** | accepted |
| **Owner** | kjoshi |
| **Created** | 2026-06-13 |
| **Last updated** | 2026-06-13 |
| **Related features** | feat-010 (this) · consumes feat-002/003/006 · fills feat-008's reserved `ckg_decisions` · LLM pass is feat-012-style |
| **Related ADRs** | ADR-0001 (layering), ADR-0004 (provenance), ADR-0005 (locked kinds) |

---

## 1. Context

Differentiator #1, the research's strongest finding (§3.3): across 15+ surveyed
tools, **none** connects architecture decision records to the code they govern.
The expensive agent failure: refactoring code a documented decision forbids,
because the decision lived in `docs/adr/0007-*.md` and the agent only retrieved
`auth.py`. All the kinds are reserved (feat-001): `Decision`/`DocChunk` nodes,
`GOVERNS`/`SUPERSEDES`/`DESCRIBES` edges; feat-008 reserved `ckg_decisions`.

**The headline works without embeddings.** The killer path — "agent touching
`payments/` is told *ADR-0012 governs this* before it writes a line" — is
**graph expansion**: a `ckg_search` vector hit on payment code → follow
`GOVERNS` one hop → the `Decision` surfaces. No doc-text embedding required.
That's what makes a tight MVP possible: ingest ADRs into `Decision` nodes with
**parsed** `GOVERNS` edges to the code they mention, wire one edge-kind into
retrieval, and expose `ckg_decisions`. Semantic search *over* decision prose
(embedding `DocChunk`s) and the LLM inference pass are deferred follow-ups.

## 2. Goals

- `agentforge_graph.knowledge` — a new engine package, **zero `agentforge`
  imports** (ADR-0001). ADR markdown → `Decision` nodes (+ body `DocChunk`s) +
  `GOVERNS`/`SUPERSEDES` edges, all `parsed` provenance.
- **Format-tolerant parse:** MADR / Nygard / adr-tools (frontmatter + sections),
  auto-detected; unparseable ADRs still become a `Decision` (degrade, don't
  drop). Parse-rate counted in `IndexReport`.
- **Precise mention linking:** backtick/bare repo-relative paths and qualified
  names in the ADR body, matched against the code graph — **unambiguous matches
  only** become `GOVERNS` edges (ambiguous mentions are counted, not guessed).
- **Rides the store's per-file machinery** (ADR-0004/feat-004): each ADR is
  upserted as its own `FileSubgraph` keyed by its path (`origin_path`), so a
  changed ADR re-ingests and a deleted ADR's `Decision`/edges vanish — reusing
  `upsert`/`delete_file`, no feat-004 `ChangeDetector` surgery.
- **Retrieval surfacing:** `context` mode follows `GOVERNS` one hop by default;
  `Decision` items render with a `[status, date]` prefix.
- Surfaces: `CodeGraph.decisions(scope, status)`, `ckg decisions` CLI,
  `ckg_decisions` MCP tool (added to `ALL_TOOLS`). `knowledge:` config.
- ≥90% coverage; `mypy --strict`; ruff.

## 3. Non-goals (explicit follow-ups)

- **Embedding `DocChunk`s** for semantic search over decision prose — the
  MarkdownChunker + embed-pipeline doc path. MVP creates `DocChunk` nodes
  (body text in attrs, for rendering) but does **not** embed them, so a purely
  architectural query with no matching *code* hit won't surface a decision yet
  (the `ckg_decisions` tool covers direct decision queries meanwhile).
- **LLM `infer_governs` pass** (decisions with zero parsed links → agent matcher
  against repo-map candidates) — off-by-default, budgeted, a feat-012-style
  `Enricher`. Follow-up.
- **General `doc_globs` / docstrings / commit-message** ingestion + `DESCRIBES`
  production — same machinery, later. (`DESCRIBES` *is* added to the retrieval
  expansion list now, harmlessly, so no retriever change when it ships.)
- **Doc-incremental-by-hash** — MVP re-ingests all ADRs each index (they're few
  and small; upsert is idempotent). Per-hash skip is a later optimization.
- Authoring/managing ADRs (we read, not write); stale-doc reporting UI.

## 4. Proposal

### 4.1 Package layout

```
src/agentforge_graph/knowledge/
  __init__.py        # KnowledgeIngestor, Decision/DocChunk builders, DecisionInfo
  adr.py             # ADRParser: markdown frontmatter + sections + status/date/supersedes
  mentions.py        # extract code/path/qualified-name mentions from ADR body
  ingest.py          # KnowledgeIngestor: discover ADRs → per-file subgraph → upsert; GC vanished
src/agentforge_graph/
  config.py              # + KnowledgeConfig
  ingest/codegraph.py    # run KnowledgeIngestor in index()/refresh(); + decisions()
  ingest/report.py       # IndexReport + decisions_indexed / governs_resolved / mentions_unresolved
  retrieve/retriever.py  # context mode also follows GOVERNS/DESCRIBES; render Decision items
  serve/tools.py         # + CkgDecisions, in ALL_TOOLS
  serve/engine.py        # + decisions() passthrough
  cli.py                 # + `ckg decisions`
tests/knowledge/         # MADR/Nygard fixtures + golden + linking-precision + integration
```

### 4.2 ADR parse (`adr.py`)

`ADRParser.parse(path, text) -> ParsedADR` (a dataclass, not a graph type):

- **Frontmatter:** if the file starts with a `---` YAML block, `yaml.safe_load`
  it (pyyaml is already a dep) → `status`, `date`, `supersedes`/`superseded-by`,
  `title`. (MADR puts these in frontmatter.)
- **Sections / Nygard:** else scan headings — `# <n>. <title>` or `# <title>`,
  a `## Status` / `Status:` line (`accepted|proposed|superseded|deprecated|
  rejected`, case-insensitive), a date (ISO `YYYY-MM-DD` anywhere in a Status/
  Date line), and a "Supersedes ADR-0007" / "Superseded by" line.
- **Body:** the remaining markdown, split into heading-bounded sections for
  `DocChunk`s.
- Robust: missing fields default (`status="proposed"`, `date=""`); a file that
  yields no recognisable ADR shape still produces a `Decision` titled from its
  filename (counted as a low-confidence parse). Status normalised to the locked
  set.

### 4.3 Mention extraction & linking (`mentions.py`)

From the ADR body, collect candidate mentions:

- **Backtick spans** `` `…` `` and **bare tokens** that look like a
  repo-relative path (`src/app/payments.py`, contains `/` and a known code
  extension) → resolve to a `FILE` node.
- **Qualified names** (`app.auth.login`, `Auth.login`, `PaymentService`) → an
  exact symbol-name match.

Resolution is **graph-driven and precise** (spec §4.3): the ingestor builds,
once per run, `path → file-id` and `name → [symbol-ids]` indices from the code
graph (a single `GraphQuery(limit=_ALL)`). A path mention resolving to exactly
one `FILE` → `GOVERNS` Decision→File. A name resolving to exactly one symbol →
`GOVERNS` Decision→Symbol. **Ambiguous or unresolved mentions are counted
(`mentions_unresolved`), never guessed** (ADR-0004 — no fake `parsed` edges).

### 4.4 Ingestion as a per-ADR subgraph (`ingest.py`)

`KnowledgeIngestor.ingest(store, repo, commit, config) -> KnowledgeStats`:

1. **Discover** files under `knowledge.adr_globs` (default `docs/adr/**/*.md`,
   `docs/decisions/**/*.md`).
2. For each ADR build a `FileSubgraph` keyed by the ADR path:
   - `Decision` node — id `SymbolID.for_symbol("doc", repo, adr_path,
     "decision.")`, `attrs={title, status, date, path, adr_id}`, span = whole
     file. (`"doc"` lang slug keeps decision ids in their own namespace; the
     path field still drives `delete_file`/`upsert`.)
   - `DocChunk` nodes for body sections (id `…"docchunk(<n>)."`, `attrs={path,
     heading, text}`), `CONTAINS` Decision→DocChunk. (Created, **not embedded**
     at MVP.)
   - `GOVERNS` Decision→{File,Symbol} from resolved mentions; `SUPERSEDES`
     Decision→Decision from the supersedes link (target id derived from the
     referenced ADR's path/number when resolvable).
   - All `Provenance.parsed("adr-parser", commit)`.
   - `store.upsert(subgraph)` — origin_path = the ADR path, so a re-ingest
     replaces it and `delete_file` drops it.
3. **GC vanished ADRs:** query existing `Decision` nodes, `delete_file` any
   whose path is no longer present. (Self-contained; no feat-004 dependency.)

Run in **both** `CodeGraph.index` and `CodeGraph.refresh`, *after* code
indexing (so the mention indices see current code). Re-ingesting every ADR each
run is cheap and keeps `GOVERNS` consistent with code that changed/disappeared
(a `GOVERNS` to a deleted symbol simply isn't recreated). `IngestPipeline` is
untouched; this is a sibling pass like the framework extractor, but over a
different file set.

> Why upsert-by-path instead of `store.add` (path-less)? So edits and deletes
> of ADRs are handled by the same per-file machinery code uses — decisions stay
> correct across incremental runs instead of accumulating.

### 4.5 Retrieval wiring (`retriever.py`)

- Add `GOVERNS` and `DESCRIBES` to `context` mode's default edge list (direction
  stays `both`, so a retrieved code symbol expands to its governing decisions via
  incoming `GOVERNS`). `DESCRIBES` is inert until a later pack produces it.
- When building a `ContextItem` for a `Decision` node, render with a prefix:
  `code = f"[{status}, {date}] {title}"` (+ a body excerpt if present), so the
  agent sees status/date inline. Decisions are scored by the `GOVERNS` edge
  weight (parsed) like any expansion edge.

### 4.6 Surfaces (`decisions()`, CLI, MCP, config, report)

- `CodeGraph.decisions(scope: str|None, status: str|None) -> list[DecisionInfo]`
  — query `Decision` nodes, filter by path-prefix `scope` (a decision is in
  scope if it *governs* a symbol under `scope`, or its own path is under it) and
  `status`; return `{adr_id, title, status, date, path, governs: [ids]}` sorted
  by (status, date).
- `ckg decisions [--scope --status]` — a table `STATUS  DATE  ADR  title`.
- `CkgDecisions(_CkgTool)` (`ckg_decisions`, `DecisionsInput{scope?, status?}`)
  → JSON via the staleness envelope; added to `ALL_TOOLS`. `engine.decisions()`
  passthrough.
- `KnowledgeConfig` (`KEY="knowledge"`): `enabled: bool = True`,
  `adr_globs: list[str] = ["docs/adr/**/*.md", "docs/decisions/**/*.md"]`.
  (`doc_globs`, `commit_messages`, `infer_governs`, `infer_budget_usd` are
  declared in the spec for follow-ups; MVP reads only `enabled`/`adr_globs`.)
- `IndexReport += decisions_indexed, governs_resolved, mentions_unresolved`;
  `_format_report` prints a `decisions:` line.

## 5. Alternatives considered

| Option | Why not |
|---|---|
| Decisions via `store.add` (path-less facts) | Then edits/deletes of an ADR don't invalidate its `Decision`/edges; they'd accumulate. Per-ADR `upsert` reuses the per-file delete/replace machinery. |
| Add `.md` to a language pack so ADRs ride `iter_files` | Pollutes the code file set + the resolver/repomap with docs; ADRs need bespoke parsing, not tree-sitter. A sibling pass keeps code clean. |
| Embed `DocChunk`s in the MVP | The headline (governed-symbol → decision) is pure graph expansion; embedding doc prose is real but separable value. Defer to keep the MVP tight. |
| LLM-infer `GOVERNS` now | Spec: off by default, `llm` provenance, budgeted — a feat-012-style enricher. Parsed links first. |
| Fuzzy mention matching | Ambiguous links pollute trust (ADR-0004). Unambiguous-only; count the rest. |

## 6. Migration / rollout

Additive: new package, new optional `knowledge:` config (absent → enabled with
default ADR globs), kinds already reserved (no schema bump). `Decision` ids use
a `"doc"` lang slug — a new namespace, no collision with code. First `ckg index`
after the feature populates decisions; repos with no `docs/adr/**` get nothing
(negative path tested), exactly as before. Retrieval gains `GOVERNS` expansion —
strictly additive (no decisions → no new items).

## 7. Risks

| Risk | Mitigation |
|---|---|
| ADR formats in the wild are messy | Best-effort detect; unparseable → a `Decision` from the filename (degrade, not drop); parse stats in `IndexReport`. |
| Inferred links pollute trust | MVP emits **only parsed** `GOVERNS`; the LLM pass (deferred) is `llm` provenance + confidence + off by default. |
| Doc-chunk volume dilutes code search | Not embedded at MVP, so zero dilution; when embedded, `source_type: doc` filter + code-weighted modes (feat-006). |
| Mention false-positives (a name that's also an English word) | Unambiguous-exact-match only; ambiguous counted, not linked. |
| GOVERNS to a symbol that later disappears | Re-ingest each run + edge MATCH drops edges to missing endpoints → consistent with code state. |

## 8. Open questions (decisions for review)

1. **Scope the first PR to ADR ingestion + parsed GOVERNS/SUPERSEDES + retrieval
   surfacing + `ckg_decisions`** (defer DocChunk embedding, general docs/
   docstrings, commit messages, LLM infer)? Proposed: **yes**.
2. **ADRs ingested as per-file `upsert` subgraphs** (ride feat-004 delete/replace)
   vs path-less `store.add`? Proposed: **per-file upsert**.
3. **`GOVERNS` (+ inert `DESCRIBES`) in the default `context` expansion**, one hop?
   Proposed: **yes** (the whole point — auto-surface governing decisions).
4. **Unambiguous-only mention linking, ambiguous counted**? Proposed: **yes**.
5. **`ckg decisions` CLI + `ckg_decisions` tool + `CodeGraph.decisions()`** this
   PR? Proposed: **yes**.

## 9. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-13 | MVP = ADR ingestion + parsed GOVERNS/SUPERSEDES + retrieval + `ckg_decisions`; embedding/LLM/commit-msgs deferred | Headline value is graph expansion, not embedding; keeps the PR tight, same "core then enrich" path as prior features |
| 2026-06-13 | ADRs upserted as per-ADR `FileSubgraph` (origin_path = ADR path) | Reuses `upsert`/`delete_file` → edits & deletes correct under feat-004 with no ChangeDetector change |
| 2026-06-13 | Sibling ingestion pass (not a language pack) over `adr_globs` | Keeps the code file set / resolver / repomap free of docs; ADRs need bespoke parsing |
| 2026-06-13 | Graph-driven, unambiguous-only mention linking | Precise `parsed` edges (ADR-0004); ambiguous counted, never guessed |
| 2026-06-13 | `GOVERNS`+`DESCRIBES` added to default context expansion; Decision rendered with `[status, date]` | The differentiator: a code hit auto-surfaces its governing decision with its status |
| 2026-06-13 | `Decision` ids use a `"doc"` lang slug | Separate namespace; path still drives upsert/delete |

## 10. Chunk plan (the single feat-010 PR)

| Chunk | Commit | Contents |
|---|---|---|
| 0 | `chore(010): KnowledgeConfig + knowledge package skeleton; design accepted` | `KnowledgeConfig`; `knowledge/__init__`; this doc → accepted |
| 1 | `feat(010): ADR parser (MADR/Nygard, frontmatter + sections)` | `adr.py`; golden parse tests (title/status/date/supersedes) on fixtures |
| 2 | `feat(010): mention extraction + precise graph linking` | `mentions.py`; path/backtick/qualified-name resolution; ambiguous-not-linked unit tests |
| 3 | `feat(010): KnowledgeIngestor — per-ADR subgraph + vanished GC` | `ingest.py`; Decision/DocChunk/GOVERNS/SUPERSEDES; upsert + delete; report counters |
| 4 | `feat(010): run in CodeGraph index/refresh + decisions()` | wire the pass (after code), `CodeGraph.decisions`; incremental + edit/delete test |
| 5 | `feat(010): retrieval surfacing (GOVERNS expansion + Decision render)` | `_MODE_EDGES` += GOVERNS/DESCRIBES; Decision item render; integration test (governed symbol → decision; ungoverned → none) |
| 6 | `feat(010): ckg decisions CLI + ckg_decisions MCP tool` | CLI table + tool + engine passthrough; locked tool-set update |
| 7 | `test(010): layering + negative + format matrix` | `knowledge` layering; no-ADR repo; MADR/Nygard/adr-tools fixtures |
| 8 | `docs(010): impl status + tracker; design accepted` | spec status; TRACKER; this doc accepted |

## 11. References

- Spec: `docs/features/feat-010-adr-and-docs-ingestion.md`
- ADRs: 0001 (layering), 0004 (provenance), 0005 (locked kinds)
- feat-002/003 (`upsert`/`delete_file`, `FileSubgraph`), feat-006 (retrieval
  expansion + `ContextItem`), feat-008 (`ckg_decisions` reserved)
- Research §3.3 (the gap — verified absent across the survey); MADR / adr-tools /
  Nygard ADR formats
