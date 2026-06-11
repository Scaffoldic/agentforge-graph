# CLAUDE.md — agentforge-graph

> Entry point for AI assistants working on **agentforge-graph**, a
> Code Knowledge Graph (CKG) engine + agent toolset built on the
> AgentForge framework (agentforge-py 0.2.4). This is an **agent
> project** (it consumes the framework), not a framework project.

## Read first, in order

1. [`../../../AGENTS.md`](../../../AGENTS.md) — workspace meta rules.
2. [`../../../.claude/development-pipeline.md`](../../../.claude/development-pipeline.md)
   — the abstract per-feature workflow every project follows
   (pick → branch → analyse → design → implement → test → commit → PR
   → merge), and the `.claude/state/` format.
3. `.claude/state/current.md` — active feature, branch, what's done,
   what's pending. **Local-only, git-ignored**; may be absent on a
   fresh clone — create it when you start tracking work.
4. [`../docs/features/TRACKER.md`](../docs/features/TRACKER.md) —
   status board + dependency DAG; tells you what's ready to pick.
5. [`../docs/features/README.md`](../docs/features/README.md) +
   the active [`../docs/features/feat-NNN-*.md`](../docs/features/) spec.
6. [`../docs/adr/`](../docs/adr/) — the 9 architecture decisions.
7. [`../docs/open-source-ckg-research.md`](../docs/open-source-ckg-research.md)
   — the research that motivates the design.

## Project-specific notes

- **Tooling is `uv`, not pip.** Install: `uv sync` (base) /
  `uv sync --extra engine`. Run the framework CLI as
  `uv run agentforge …`, the agent CLI as `uv run ckg …`.
  `agentforge add module` does **not** work here (it shells out to
  `pip`, absent in uv venvs) — declare modules in `pyproject.toml`
  and `uv sync` instead.
- **Two config files, on purpose.** `agentforge.yaml` is framework
  config (strict validator — no unknown keys). `ckg.yaml` is this
  agent's own engine config (store/ingest/chunking/embed/retrieve/
  serve), read by the `agentforge_graph` package.
- **Framework learnings go in `docs/framework/`** — local-only,
  git-ignored. Log any framework bug/hack/workaround/missing-feature
  there as you hit it (baseline: agentforge-py 0.2.4).
- **Reuse framework rails, don't reinvent.** `Tool` ABC + MCP
  (feat-008), `Agent` + `budget_usd` (feat-010/012 enrichment),
  reranker (feat-006). Keep the deterministic engine core
  (`core`/`ingest`/`store`/`retrieve`) free of `agentforge` imports
  (ADR-0001).
- **Feature numbering is fixed** by `docs/features/`. Branch
  `feat/NNN-slug` must match an existing spec filename — never invent
  numbers. One feature = one branch = one PR.
- Use `Read`/`Edit`/`Glob`/`Grep`, not Bash `cat`/`find`/`sed`.
  Never `--no-verify` without explicit authorization.
