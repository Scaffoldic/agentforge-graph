# design-enh-024: remote repo sources (git/github URL)

Mirrors [ENH-024](../enhancements/ENH-024-remote-repo-sources.md).

## Goal

A `workspace.yaml` member can be a git/github URL instead of a local path; the
build clones it into a managed checkout under the workspace and builds it — so the
org graph can be stood up from a list of URLs, using the operator's ambient git
auth.

## Pieces

### `serve/checkout.py` (framework-free, subprocess only)

- `ensure_checkout(git_url, dest, *, ref, fetch, shallow) -> Path` — clone on the
  first run (shallow `--depth 1` unless a `ref` is pinned), else fetch + (`checkout
  <ref>` | `pull --ff-only`). Shells out to `git`; **never handles credentials**
  (inherits ssh agent / credential helper). Raises `CheckoutError` with git's
  stderr on failure.
- `ensure_gitignore(dir)` — the managed checkout area (`.checkouts/`) is fully
  git-ignored (`*`).

### `serve/workspace.py`

- `WorkspaceMember`: `repo` now optional; new `git` + `ref`; a `model_validator`
  enforces **exactly one** of `repo`/`git`.
- `WorkspaceConfig.checkouts_dir` = `<manifest-dir>/.checkouts`.
- `member_repo(m)` returns the checkout path for a git member
  (`checkouts_dir/<slug>`), the resolved local path otherwise — a **pure** path
  resolver (no cloning), so federation/serve read paths are unaffected.
- `prepare_member(m, *, fetch, shallow)` — the side-effecting step: clones/fetches
  a git member (via `ensure_checkout`) and returns its path; a no-op for local.

### `store/location.py`

- Factored `slug_from_remote(url) -> str | None` out of `repo_key` and reused for
  the checkout dir, so a repo keys the **same** whether cloned or local
  (`git@github.com:acme/gateway.git` → `acme-gateway`).

### `cli.py`

- `_workspace_run` calls `ws.prepare_member(m, fetch=…)` before building each
  member. `--no-fetch` (on `build`/`index`) builds git members against the
  existing checkout, offline.

## Resolved decisions

| Decision | Rationale |
|---|---|
| Shell out to `git`, never handle creds | The operator's ssh agent / credential helper already works; re-implementing auth is risk with no upside. |
| Checkout under `<workspace>/.checkouts/<slug>`, git-ignored | Discoverable, scoped, wipeable; never committed. Same slug as `repo_key` so central-store namespacing lines up. |
| Shallow clone unless `ref` pinned | Fast by default; a pinned ref may need history (and feat-009 temporal needs depth — noted). |
| `member_repo` pure; cloning in `prepare_member` | Read paths (federation serve) must not trigger network I/O; only the build does. |
| Config from the cascade, not the clone's own file | A cloned third-party repo's config isn't auto-adopted; workspace `defaults:` are authoritative (ENH-022). |

## Out of scope (noted)

- Submodules, monorepo sub-paths, credential vaulting.
- Shallow-vs-temporal interaction beyond the note (history needs depth).
- Live-network tests — all tests clone a **local** git repo fixture.

## Tests

`tests/serve/test_workspace_checkout.py`: member validation (exactly one
repo/git); `member_repo` → `.checkouts/<slug>`; `ensure_checkout` clone +
idempotent re-run + `.gitignore`; `ref` pin (tag); end-to-end `ckg build
--workspace` clones a git member and indexes it. Federation regression green
(local-repo workspaces unaffected). Gate: 831 passed, 94.70% cov, mypy + ruff clean.
