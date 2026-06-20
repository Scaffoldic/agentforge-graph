# ENH-017: surface framework-upgrade drift (so consumers can clean workarounds)

| Field | Value |
|---|---|
| **ID** | ENH-017 |
| **Value/Impact** | Medium (developer-experience for every AgentForge consumer) |
| **Effort** | S–M (upstream) |
| **Status** | proposed — **upstream recommendation** (file here, then post to `agentforge-py`) |
| **Area** | framework / upstream (`agentforge-py`) |
| **Relates to** | the local `docs/framework/` workaround log; ENH-005, the config consolidation |

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
