# design-enh-021: workspace-driven build commands

Mirrors [ENH-021](../enhancements/ENH-021-workspace-build-commands.md).

## Goal

Teach the write verbs the `--workspace` flag the read verbs already have, and add
`ckg build` — one command that indexes (+ embeds where enabled, + enriches with
`--enrich`) a whole workspace, with a per-member report.

## Approach: a single workspace runner over the existing per-repo paths

All four verbs funnel into one helper in `cli.py`:

- `_run_member_steps(repo, config, steps, *, full) -> str` — runs an ordered
  subset of `("index", "embed", "enrich")` for one repo via the existing
  `CodeGraph.index` / `.open` + `.embed` / `.enrich`, returning a one-line
  summary. `embed` honors ENH-023 (`cg.embed()` returns `disabled` when off).
- `_workspace_run(args, *, steps, full)` — loads the `WorkspaceConfig`,
  **preflights every member up front** (ENH-026) and refuses before any work,
  then runs each member with its **resolved config** (ENH-022
  `resolve_member_config`), **skipping read-only members** (ENH-018), continuing
  past a failing member, and printing `_print_member_report`.

The verb handlers branch on `args.workspace`:

| Verb | workspace steps |
|---|---|
| `ckg index --workspace` | `("index",)` (+ `"embed"` if `--embed`) |
| `ckg embed --workspace` | `("embed",)` |
| `ckg enrich --workspace` | `("enrich",)` (pattern tags) |
| `ckg build [--workspace]` | `("index","embed")` (+ `"enrich"` if `--enrich`) |

`ckg build` also works on a single repo (no `--workspace`): same steps, with the
existing read-only refusal + `_preflight_or_exit` gate.

## Resolved decisions

| Decision | Rationale |
|---|---|
| Serial member builds | Simple, legible output, bounded resources. Parallel build is a noted follow-on. |
| Continue-on-error → exit 1 | One bad member shouldn't abort the batch; failures are in the report with the reason. Preflight errors (config) exit 2 and block before any work. |
| Read-only members skipped, not failed | A consume-only member (ENH-018) is intentional, not an error. |
| `embed` step respects `embed.enabled` | Via `cg.embed()` (ENH-023) — a structure-only member reports "embed disabled". |
| enrich = pattern tags in workspace mode | Summaries/decisions stay single-repo flags; keeps the batch verb simple. |

## Out of scope (noted)

- Parallel member builds.
- Per-member `--lang`/`--include`/`--exclude` (those live in each member's config).
- `ckg status --workspace` summary view (spec lists it; deferred — `ckg doctor
  --workspace` already gives the readiness view; freshness fan-out can follow).

## Tests

`tests/serve/test_workspace_build.py`: build indexes+embeds all members; index-only
skips embed; per-member `embed: false`; continue-on-error (unknown driver →
member FAILED, healthy member still built, exit 1); preflight blocks the whole
workspace before any work; read-only member skipped; single-repo `ckg build`.

Gate: 826 passed, 94.79% cov, mypy + ruff clean.
