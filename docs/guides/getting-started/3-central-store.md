# Getting started 3 — a central store (hosted / shared index)

> **TL;DR:** set `store.central_root` (or a server backend) so the index lives
> **outside** the repos — built once by a team/CI and consumed by many
> developers and agents `--read-only`. Each repo gets a stable, collision-free
> subdir; nobody mutates the shared index by accident.
> **Prereqs:** [1 — a single repo](1-single-repo.md).

By default the index is a gitignored `.ckg/` *inside* each repo — perfect for one
developer. To make CKG an **org-level shared knowledge base** — build once,
serve many — decouple *where the index lives* from the repo.

## The three deployment shapes

| Shape | Config | Who builds | Who reads |
|---|---|---|---|
| **Laptop** (default) | `store.path: .ckg` | the dev | the dev |
| **Central, embedded** | `store.central_root: /shared/ckg` | a team / CI | many, `--read-only` |
| **Central, server** | `store.graph.driver: surrealdb` (or neo4j / pgvector) | a team / CI | many, `--read-only` |

## 1. Host the index centrally (embedded)

Point a config at a shared root (absolute path). In each repo's `ckg.yaml` — or
the `app:` block of `agentforge.yaml`:

```yaml
store:
  central_root: ~/.agentforge/ckg      # absolute → artifacts live here, not in the repo
```

```bash
ckg index /path/to/orders
ckg status /path/to/orders             # store: …/ckg/<repo-key>  (central)
```

The `.ckg/` artifacts move to `central_root/<repo-key>`. The **repo key** is
derived from the git remote (`org/repo` — the same on every machine) or, with no
remote, from the path — so pointing **many** repos at one `central_root` gives
one collision-free subdir each, never a clash.

## 2. Consume read-only (build once, serve many)

A team/CI builds the central index where it's writable; everyone else consumes it
**read-only** so the shared knowledge can't be mutated by accident:

```yaml
store:
  read_only: true            # or pass --read-only, or set $CKG_READ_ONLY=1
```

```bash
ckg query "where is retry handled" --repo /path/to/orders   # reads fine
ckg index /path/to/orders                                   # refuses: consume-only (exit 2)
```

Read verbs (`query` / `map` / `routes` / `serve-mcp` …) work; the write verbs
(`index` / `embed` / `enrich`) refuse, and opening a *missing* index errors
rather than silently creating one.

## 3. Or host on a server (SurrealDB / Neo4j / pgvector)

For a real shared database instead of a shared directory, switch the backend.
**SurrealDB** is multi-model — graph + vectors in one server:

```yaml
store:
  graph:   { driver: surrealdb, config: { url: ws://your-host:8000 } }
  vectors: { driver: surrealdb, config: { url: ws://your-host:8000 } }
```

Install the extra (`pip install agentforge-graph[surrealdb]` / `[neo4j]` /
`[pgvector]`). Same commands, same conformance — only *where the bytes live*
changes. → [storage backends](../09-storage-backends.md) for connection details
and secrets handling.

## 4. The typical org topology

```
   CI / owning team                developers + agents
   ───────────────                 ───────────────────
   ckg index <repo>      ──▶   central store   ──▶   ckg query / serve-mcp --read-only
   (writable)                (shared dir or DB)        (consume-only, many clients)
```

Combine with a [workspace](2-workspace.md) to serve the whole org — federated and
hosted — from one MCP endpoint: each member's `ckg.yaml` points at the shared
`central_root` (or server), and `ckg serve-mcp --workspace` reads it read-only.

## Notes

- Default behavior is unchanged: with no `central_root` set, the index is the
  in-repo `.ckg/` exactly as before.
- An absolute `store.path` still relocates a *single* repo's index;
  `central_root` is the multi-repo, no-collision way.
- `ckg status` prints the resolved location and a `(central)` marker.
