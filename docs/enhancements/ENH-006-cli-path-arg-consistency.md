# ENH-006: unify the repo-path argument across `ckg` subcommands

| Field | Value |
|---|---|
| **ID** | ENH-006 |
| **Value/Impact** | Medium (DX — surprising, costs every new user a `--help`) |
| **Effort** | S |
| **Status** | **done** (2026-06-15) |
| **Area** | `cli` |
| **Relates to** | feat-002/006/007/008 (the subcommands) |

## Motivation

The CLI uses **three different conventions** for "which repo":

| Convention | Subcommands |
|---|---|
| positional `[path]` | `index`, `status`, `embed`, `enrich`, `query`, `map`(?), `routes`, `decisions`, `summaries`, `tagged` |
| `--path PATH` | `map` |
| `--repo PATH` | `serve-mcp` |

Found in W1 validation: `ckg status --path /tmp/click` errors (`status` wants a
positional), while `ckg map --path …` is required (`map` has no positional).
Inconsistency like this is a small but constant papercut.

## Proposed change

Pick one convention and make the others aliases for backward-compatibility:

- Recommended: **positional `[path]` defaulting to `.`** everywhere (matches most
  subcommands today), and keep `--path` / `--repo` as accepted aliases so no
  existing invocation breaks.
- Verify with a test that every subcommand accepts the same path form.

## Acceptance criteria

- The same path argument works on every subcommand.
- Existing `--path` (`map`) and `--repo` (`serve-mcp`) invocations still parse.
- A parser test enforces the convention so it can't drift again.

## Resolution (2026-06-15)

Added `_add_repo_arg(parser, *, positional=True)` in `cli.py`: a positional
`[path]` (default `.`) plus `--path` / `--repo` aliases (shared dest
`path_alias`). `main()` calls `_resolve_repo_path` to collapse them with
precedence **positional > `--path`/`--repo` > `.`**. `serve-mcp` now reads
`args.path` (was `args.repo`); `query` / `tagged` keep their leading positional
and take the path via the aliases only. `tests/test_cli_path_args.py`
parametrizes every subcommand over all three forms + precedence + the legacy
`--path`/`--repo` invocations so the convention can't drift. 398 passed, 97%.

## Notes

Trivial but worth doing before 0.1 — the CLI is part of the production surface.
