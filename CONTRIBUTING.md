# Contributing to agentforge-graph

Thanks for helping build the Code Knowledge Graph. This guide gets you (or your
AI assistant) productive fast. Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
first for the system map; this doc is the *how to work on it*.

---

## 1. Setup

Tooling is **`uv`, not pip**.

```bash
uv sync --extra engine --extra bedrock     # engine + native wheels + boto3
cp .env.example .env                        # optional: AWS creds for live model tests
```

- `agentforge add module` does **not** work here (it shells out to pip, absent
  in uv venvs). Declare deps in `pyproject.toml` and `uv sync`.
- Run the engine CLI as `uv run ckg …`, the framework CLI as `uv run agentforge …`.

## 2. The quality gate (run before every PR)

CI runs exactly this; keep it green locally:

```bash
uv run pytest          # tests, ≥90% coverage floor (enforced via pyproject)
uv run mypy src/agentforge_graph     # --strict
uv run ruff format . && uv run ruff check .
```

- **No model calls or cloud creds in CI.** Deterministic fakes (`FakeEmbedder`,
  `ScriptedJudge`, `ScriptedSummarizer`) stand in for the live adapters.
- **Live model tests are env-gated:** `CKG_LIVE_BEDROCK=1` (embeddings),
  `CKG_LIVE_AGENT=1` (Claude judge/summarizer). Run locally with AWS creds.

## 3. The development pipeline (one feature = one branch = one PR)

We follow a design-first, chunked, validated flow:

1. **Pick** a unit of work (a feature spec in `docs/features/`, a bug, an
   enhancement). Never invent feature numbers — branch `feat/NNN-slug` must match
   an existing spec; `bug/<slug>` and `enh/<slug>` for the others.
2. **Design** (for features): write `docs/design/design-NNN-slug.md` and get it
   approved *before* coding. Bugs/enhancements use their `docs/<category>/` doc
   as the spec.
3. **Branch** from fresh `main`: `git checkout main && git pull && git checkout -b feat/NNN-slug`.
4. **Implement in chunks** — several focused commits on the branch.
5. **Validate** — the full quality gate above, plus dogfood the change on a real
   repo when it's user-facing.
6. **One PR**, opened only when complete and green. Squash-merge.

Findings from evaluation are filed under `docs/bugs/`, `docs/enhancements/`,
`docs/known-limitations/` — each directory has a `README.md` template.

## 4. The one architectural rule you must not break (ADR-0001)

**The deterministic engine never imports `agentforge`.** Packages `core`,
`config`, `ingest`, `store`, `chunking`, `embed`, `retrieve`, `repomap`,
`frameworks`, `knowledge` are framework-free and have a layering test that
parses their imports. Only **`serve`** (MCP/Tools) and **`enrich`** (budget rails
+ LLM) may import `agentforge`. Keep new engine code framework-free; if you need
the framework, you're in the wrong layer.

## 5. Playbooks — how to add common things

### Add a language pack
1. `src/agentforge_graph/ingest/packs/<lang>/`: `__init__.py` (a `LanguagePack`),
   `structure.scm` (defs/imports), `references.scm` (calls). Pick
   `module_style="dotted"` (Python/Java) or `"relative"` (TS/JS).
2. Register it in `packs/__init__.py` (`BUILTIN_PACKS`).
3. Add a golden test + the `ExtractorConformance` suite. Mirror `packs/typescript/`.
4. Note: drive parsing with `Parser(get_language(name))`, never `get_parser()`
   (tree-sitter-language-pack ABI quirk — see `docs/framework/`).

### Add a framework pack (routes/ORM/DI)
1. `src/agentforge_graph/frameworks/packs/<name>/`: a `FrameworkPack` with
   `detect()` (dep manifest + import markers) and `extract()` emitting framework
   nodes/edges. Mirror `packs/fastapi/`.
2. Register in `frameworks/registry.py`. Facts are **merged into the
   `FileSubgraph`** so they ride incremental indexing automatically.

### Add a storage backend (Neo4j, SurrealDB, pgvector, …)
1. Implement `GraphStore` and/or `VectorStore` (`core/contracts.py`).
2. Pass `GraphStoreConformance` / `VectorStoreConformance` (`core/conformance.py`).
3. Register via the entry-point group `agentforge_graph.graph_drivers` /
   `…vector_drivers`, or add to the built-ins in `store/registry.py`.
4. Users select it with `store.graph.driver: <name>` in `ckg.yaml`.

### Add a model provider (OpenAI, local, …)
The model layer is a provider registry (ENH-003), mirroring storage drivers — no
core change needed:
1. Implement `Embedder` (`embed/base.py`) and/or `PatternJudge` / `Summarizer`
   (`enrich/judge.py`, `enrich/summarizer.py`).
2. Expose a builder `(EmbedConfig|EnrichConfig) -> instance` under the matching
   entry-point group: `agentforge_graph.embedder_providers`,
   `agentforge_graph.judge_providers`, or `agentforge_graph.summarizer_providers`
   (or add it to the built-ins in `embed/registry.py` / `enrich/registry.py`).
3. Users select it from `ckg.yaml`: `embed.driver: <name>` (embeddings) or
   `enrich.provider: <name>` (judge + summarizer). `scripted` is the built-in
   credential-free provider for offline runs.

### Add an MCP tool
Subclass `_CkgTool` in `serve/tools.py`, declare `name`/`description`/
`input_schema`, implement `run()`, add the class to `ALL_TOOLS`. The tool set is
locked-by-test, so update `tests/serve/test_schemas.py`.

### Add an enricher
Drain a `DirtySet` consumer, emit `llm`-provenance facts via `store.add`, run
under `BudgetPolicy`, and use `clear_outgoing` (not `add` alone) for idempotent
re-derivation. Note: don't delete+recreate stable edges on a live connection —
see the Kuzu forward-rel-scan note in `docs/framework/`.

## 6. AI-assisted development

This codebase is designed to be worked on with AI agents (Claude Code, Cursor,
Aider, …). When you point one at the repo:

- It auto-reads **[`AGENTS.md`](AGENTS.md)** (the convention file) — the
  invariants and anti-patterns. Keep that file accurate.
- Have it read **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)** for the map and
  the relevant **`docs/design/`** doc before changing a subsystem.
- Dogfood: you can run agentforge-graph **on itself** to give the assistant
  grounded context — `ckg index . && ckg serve-mcp --repo .` exposes this repo's
  own graph (decisions, routes, impact, summaries) as tools.
- Respect the gate: every AI-authored change still passes
  `pytest + mypy --strict + ruff` and follows the one-PR-per-unit pipeline.

## 7. Commit & PR conventions

- Conventional-ish prefixes: `feat(NNN):`, `fix(BUG-NNN):`, `enh(ENH-NNN):`,
  `docs(…):`, `test(…):`, `chore(…):`.
- Never push to `main` directly; never `--no-verify` without authorization.
- Keep PRs scoped to one unit; explain the *why* and how you verified.
