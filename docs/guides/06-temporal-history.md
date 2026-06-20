# Temporal — git evolution, history, and time-travel

> **TL;DR:** Record each symbol's git lifecycle — introduced / churn / authors —
> and reconstruct the graph at an earlier commit. `ckg history <symbol>`,
> `changed-since`, `--as-of`. Opt-in; off by default.

Code isn't static. agentforge-graph can record each symbol's **lifecycle** from
git history — when it was introduced, how often it churns, who touches it, and
what the graph looked like at an earlier commit (feat-009). Opt-in; off by default.

## Turn it on

```yaml
# ckg.yaml
temporal:
  enabled: true            # on + a git repo → records lifecycle to .ckg/temporal.db
  retention_commits: 1000  # prune CLOSED events older than this horizon
```

```bash
ckg index .                       # records lifecycle going forward
ckg index . --history 500         # backfill: replay the last 500 commits
ckg index . --history full        # backfill the whole history
```

History lives in a **sidecar** (`.ckg/temporal.db`); the main index schema is
unchanged, so temporal is purely additive.

## Ask about time

```bash
ckg history <symbol-id>           # introduced / last-changed / churn / authors / events
ckg changed-since v1.2.0          # symbols changed since a ref (or epoch)
ckg changed-since HEAD~50 --scope src/payments/
ckg query "refund logic" --as-of <commit>   # retrieve against the graph AS IT WAS
```

`--as-of <commit>` reconstructs the live symbol set at that commit (a symbol is
alive iff its last event ≤ C is `OPENED`) — so an agent can reason about a past
state, not just `HEAD`.

Over **MCP**, the `ckg_history` tool returns a symbol's history + what changed
since a ref as JSON.

## What it records

- **Lifecycle events** — `OPENED`/`CLOSED` per symbol, stamped with the commit +
  author time.
- **Churn & authorship** — 30/60/90-day change counts and author sets, mined from
  git and **denormalised onto the node** so retrieval can weight hot/owned code.

## Notes

- Needs a real git repo; on a non-git source temporal stays inert.
- Backfill replays blobs commit-by-commit, so a deep `--history full` on a large
  repo takes a while (it's a one-time cost; subsequent indexes are incremental).
