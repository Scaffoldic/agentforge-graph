# ENH-024: remote repo sources in the workspace (git/github URL)

| Field | Value |
|---|---|
| **ID** | ENH-024 |
| **Value/Impact** | Med–High (build the org graph from URLs, no manual checkout) |
| **Effort** | L |
| **Status** | proposed |
| **Area** | `serve/workspace`, `cli`, new `workspace/checkout` |
| **Relates to** | [THEME: org-central-knowledge](THEME-org-central-knowledge.md), ENH-021 (build commands), ENH-022 (cascade) |

> **One-liner.** Let a `workspace.yaml` member name a **git/github URL** (cloned
> over the operator's existing ssh/https access) instead of a local path; the
> build clones/fetches it into a managed checkout under the workspace and indexes
> that — so an operator can stand up the whole org graph from a list of URLs.

## Motivation

The org-central goal is "one brain across every repo the org owns." Requiring
every repo to already be checked out next to the manifest is friction at org
scale and impossible for repos the operator doesn't keep locally. Naming repos by
URL — using the ssh access the operator already has on their CLI — makes the
workspace manifest a portable, declarative description of the org's code.

## Current behavior

- `WorkspaceMember.repo` is resolved as a **filesystem path only**:
  `member_repo()` does `Path(m.repo)` and joins it to the manifest dir
  (`serve/workspace.py:67-70`). `WorkspaceMember` is `{name, repo, config}`
  (`serve/workspace.py:29-46`).
- There is **no clone/fetch logic** anywhere; a member must already exist on disk.

## Proposed change

Add an optional remote source to a member and a managed checkout area. Additive;
local-path members are unchanged.

### 1. URL members + ref pin

```yaml
members:
  - name: app
    repo: ../app                      # local path (unchanged)
  - name: gateway
    git: git@github.com:my-org/gateway.git   # ssh URL (operator's existing access)
    ref: main                                 # optional branch/tag/sha (default: remote HEAD)
  - name: orders
    git: https://github.com/my-org/orders.git
    ref: v2.3.1
```

`git:` and `repo:` are mutually exclusive per member. `ref` pins a
branch/tag/commit for reproducible builds.

### 2. Managed checkout area

URL members are cloned into a workspace-local, git-ignored checkout dir
(default `<workspace-dir>/.checkouts/<repo-key>`, using the same `repo_key()` slug
ENH-018 already derives). The build resolves the member's path to its checkout.

### 3. Update policy

- First build: **clone** (shallow by default — `--depth 1` unless `history:` is
  requested, since temporal features need depth).
- Subsequent builds: **fetch + checkout the ref** (fast-forward / detached at the
  pinned sha). A `--no-fetch` flag builds against the existing checkout offline.
- Auth is the operator's ambient git config (ssh agent / credential helper) — we
  **shell out to `git`** and inherit its auth; we never handle credentials
  ourselves.

### 4. Composes with the cascade + central store

A cloned repo has nowhere to carry our config — so its config comes entirely from
the ENH-022 workspace `defaults:` (plus any member inline overrides). Its index
lands in the central store under its `repo_key` (ENH-018), exactly like a local
member.

## Implementation sketch

- `WorkspaceMember` gains `git: str | None`, `ref: str | None`; validation that
  exactly one of `repo`/`git` is set (`serve/workspace.py`).
- New `workspace/checkout.py`: `ensure_checkout(member, workspace_dir, *,
  fetch=True, shallow=True) -> Path` — clone-or-fetch via `subprocess` to `git`,
  return the checkout path. Uses `repo_key`-derived dir; writes/refreshes a
  `.checkouts/.gitignore`.
- `member_repo()` (and ENH-021's `_each_member`) call `ensure_checkout` for URL
  members before running index/embed.
- History-dependent features (feat-009 temporal) require non-shallow — surface a
  clear note if `history` is on but the checkout is shallow.

## Surfaces

- `workspace.yaml` member `git:` + `ref:`.
- Managed `<workspace>/.checkouts/<repo-key>` (git-ignored).
- `--no-fetch` / shallow-vs-full controls on the workspace build.
- Build report shows each URL member's resolved ref + sha.

## Suggested chunk plan (one branch, multiple commits)

1. `WorkspaceMember.git/ref` + mutual-exclusion validation; tests for parsing.
2. `workspace/checkout.py` clone (shallow) into `repo_key` dir + `.gitignore`;
   tests against a **local bare repo fixture** (no network in CI).
3. Fetch/update + `ref` checkout (branch/tag/sha) + `--no-fetch`; idempotency
   tests (second build fast-forwards, pinned sha stays put).
4. Wire into ENH-021 build/`_each_member`; shallow-vs-history note; docs
   (getting-started workspace guide: "repos by URL").

## Acceptance criteria

- A member with `git:` (ssh or https) is cloned and indexed by `ckg build
  --workspace` with no manual checkout.
- `ref:` pins the build to that branch/tag/sha; re-running fetches and stays on
  the ref.
- Local-path members are unchanged; `.checkouts/` is git-ignored.
- All clone/fetch tests run against a local fixture repo (CI needs no network).

## Notes / alternatives / risks

| Concern | Note |
|---|---|
| Auth | We **never** handle credentials — shell out to `git` and inherit the operator's ssh agent / credential helper. Documented as a prerequisite. |
| Shallow vs. temporal | feat-009 history needs real depth; shallow clones disable it. Detect and warn rather than silently produce empty history. |
| Checkout location | Under the workspace dir (not a global cache) so it's discoverable, scoped, and easy to wipe; git-ignored so it never gets committed. |
| Network in CI | All tests use a local bare-repo fixture; no live network dependency. |
| Scope creep | Submodules, monorepo sub-paths, and credential vaulting are **out of scope** for v1 — named here, deferred. |

## 0.6.0 candidacy

The biggest/riskiest item in the epic; **land last**, after the local-path
workspace flow (ENH-021/022/023/026) is proven. Cleanly separable — could split to
its own follow-on if the epic gets heavy.
