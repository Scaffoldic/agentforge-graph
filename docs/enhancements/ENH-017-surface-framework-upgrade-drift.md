# ENH-017: make `agentforge upgrade` safe + surface upgrade drift

| Field | Value |
|---|---|
| **ID** | ENH-017 |
| **Value/Impact** | Med–High (every AgentForge consumer; one part is a **data-loss bug**) |
| **Effort** | S–M (upstream) |
| **Status** | **filed upstream** — [agentforge-py#114](https://github.com/Scaffoldic/agentforge-py/issues/114) (Part A, the bug) + [agentforge-py#115](https://github.com/Scaffoldic/agentforge-py/issues/115) (Part B, drift surfacing) |
| **Area** | framework / upstream (`agentforge-py`) — the `upgrade` / `fork` commands |
| **Relates to** | the local `docs/framework/` workaround log; ENH-005, the config consolidation |

> **Two parts.** **(A)** A confirmed **`agentforge upgrade` data-loss bug** —
> it clobbers forked files and `agentforge:custom` sections (details below). **(B)**
> The original request: no signal tells a consumer *which workarounds a version
> bump made removable*. (A) is the urgent one.

> This is a recommendation **for the framework**, staged in our repo first (per
> the team's process) before posting upstream to
> [`Scaffoldic/agentforge-py`](https://github.com/Scaffoldic/agentforge-py).

## Motivation

We log every framework workaround in `docs/framework/` against a baseline
version, with the intent to *remove the workaround once the framework fixes it
upstream*. In practice the cleanup is easy to **miss**: bumping the framework pin
verifies *"nothing broke"* (compat), but nothing tells the consumer *"these two
things you worked around are now fixed — delete your workarounds."*

Concretely, the 0.2.4 → 0.3.x bump silently fixed two things we'd worked around:

- the strict config validator now accepts an `app:` passthrough (we had a whole
  second config file, `ckg.yaml`, because of this);
- `MCPServer.from_http` grew a `middleware=` hook (we'd reimplemented ~60 lines of
  HTTP-serve internals to add auth).

Both shipped in 0.3.x, but **we only discovered them by manually re-reading the
source** — not from any upgrade signal. A consumer without that discipline keeps
dead workarounds (and accumulates "drift") indefinitely.

## Part A — `agentforge upgrade` clobbers forked files + custom sections (confirmed bug)

Reproduced on the 0.2.4 → 0.3.1 template upgrade (this repo, 2026-06-21):

1. `agentforge fork AGENTS.md` reported *"forked … future upgrades will skip it."*
2. `agentforge upgrade` then **re-injected `AGENTS.md` from the template anyway**
   (its log: *"re-injected 27 shared scaffold files"*), **overwriting the whole
   file — including its `agentforge:custom` block**, whose content the docs/README
   explicitly promise *"survives `agentforge upgrade`."*
3. Same for the managed runbooks (`docs/runbooks/*`): their `agentforge:custom`
   sections were wiped.

Net effect: a consumer who has followed the documented pattern (put project notes
in the custom section; `fork` files you own) **silently loses that content** on
upgrade. We only caught it by diffing; an unattended upgrade would have shipped
the loss. The data we had to hand-recover: `AGENTS.md`'s project-invariants
section + three runbook notes.

**Root cause (apparent):** the "shared scaffold re-injection" pass runs
*independently of* the per-file managed/forked/custom logic — it rewrites whole
files rather than three-way-merging the managed region and preserving
`fork` + `agentforge:custom`.

**Fix (upstream):** the re-injection pass must honor (a) **fork status** — never
touch a forked file — and (b) **`agentforge:custom` blocks** — always preserve
them verbatim, even when the managed region is replaced. A `--dry-run` that lists
*per-file* what will change (it currently prints only a one-line summary) would
also have surfaced this before any write.

## Current behavior

- `agentforge-py` ships a version bump; there is no machine- or human-readable
  **"what changed that affects you"** surface beyond reading the diff/source.
- No deprecation warnings, no `fixes:`/`closes #NN` mapping a release to the
  issues it resolves, no `agentforge upgrade --notes` / `agentforge doctor`.

## Proposed change (any one helps; in order of leverage)

1. **A CHANGELOG that tags fixes to issues** (`Fixed … (closes #86)`), so a
   consumer scanning the range between their old and new pin sees exactly which
   of their filed issues are resolved.
2. **`agentforge upgrade --notes <from>..<to>`** (or `agentforge doctor`) that
   prints the changelog slice + any deprecations between two versions — the
   "drift report" a consumer runs right after bumping the pin.
3. **Deprecation warnings** on shims/old seams the framework intends to replace,
   naming the new API (e.g. "`from_http(runner=…)` for auth is superseded by
   `middleware=`"), so the workaround announces its own obsolescence.

## Acceptance criteria

- After bumping the pin, a consumer can obtain a list of **fixed issues /
  changed surfaces** for the version range without reading source — ideally one
  command, at minimum a `closes #NN`-tagged CHANGELOG.

## Notes / alternatives

- Our side already does half of this: `docs/framework/` logs each workaround with
  the upstream issue + a "revisit on upgrade" note (see
  `docs/framework/upgrade-0.2.4-to-0.3.x.md` for the worked example). The gap is
  the **framework-side signal** that tells us *when* to revisit.
- This is low-risk and additive for the framework; (1) is essentially free.
- Part A is **not** additive — it's a correctness fix — but it's contained to the
  `upgrade` re-injection pass.

## Draft upstream issue (ready to post to `Scaffoldic/agentforge-py`)

> **Title:** `agentforge upgrade` overwrites forked files and `agentforge:custom`
> sections (data loss)
>
> **Body:**
>
> **Severity:** data loss — silent on an unattended upgrade.
>
> **Repro** (template `minimal`, framework 0.2.4 → 0.3.1):
> 1. Customize a managed file's `<!-- agentforge:custom -->` block (e.g.
>    `AGENTS.md`, a `docs/runbooks/*.md`).
> 2. `agentforge fork AGENTS.md` → *"forked … future upgrades will skip it."*
> 3. `agentforge upgrade`.
>
> **Expected:** the forked file is skipped; for still-managed files, the managed
> region is three-way-merged and the `agentforge:custom` block is preserved
> verbatim (as the runbook README promises: *"survives `agentforge upgrade`"*).
>
> **Actual:** `upgrade` logs *"re-injected N shared scaffold files"* and rewrites
> `AGENTS.md` (and the runbooks) **wholesale** — ignoring the fork and **erasing
> the `agentforge:custom` content**.
>
> **Likely cause:** the shared-scaffold re-injection pass runs independently of
> the per-file managed/forked/custom resolution and writes whole files.
>
> **Asks:**
> 1. Re-injection must respect **fork status** (never write a forked file).
> 2. Re-injection must preserve **`agentforge:custom`** blocks even when replacing
>    the managed region.
> 3. `agentforge upgrade --dry-run` should list **per-file** changes (it prints
>    only a one-line summary today), so this is visible before any write.
>
> **Related (same command, lower priority):** there's no "what changed that
> affects me" surface after a bump (e.g. a `closes #NN`-tagged CHANGELOG or
> `agentforge upgrade --notes <from>..<to>`), so consumers can't tell which of
> their filed workarounds a release made removable. See Part B.
