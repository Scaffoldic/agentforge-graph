# ENH-018: store-location choice (in-repo vs. central) + read-only consumers

| Field | Value |
|---|---|
| **ID** | ENH-018 |
| **Value/Impact** | High (the first rung to org-level central knowledge) |
| **Effort** | S–M |
| **Status** | proposed |
| **Area** | `config`, `store` (facade), `cli` |
| **Relates to** | [THEME: org-central-knowledge](THEME-org-central-knowledge.md), ENH-004 (server backends), ENH-010 (SurrealDB), feat-004 (incremental) |

> **One-liner.** Make *where the knowledge lives* a first-class, documented
> developer choice — **in-repo** (`.ckg/`, laptop default) or **central** (a
> shared dir / SurrealDB / Neo4j built once and consumed read-only) — with an
> auto-derived per-repo subdir so a central root never collides.

## Motivation

The org-central vision (build once centrally, serve many devs + agents) needs the
index to be **decoupled from the repo working copy**. Today that decoupling is
*technically* possible but undocumented, easy to get wrong (collisions), and has
no consumer-side "I only read this" mode. This enhancement turns an accidental
capability into a deliberate, safe choice.

## Current behavior

- `Store.open` computes the artifact root as **repo-relative**:
  ```python
  root = Path(repo_path) / cfg.path        # store/facade.py:44
  ```
  `StoreConfig.path` defaults to `".ckg"` (`config.py:117`).
- Because Python's `/` lets an **absolute** right operand win, setting
  `store.path: /abs/path` already escapes the repo — but:
  - **Nothing documents this**, so it's invisible to users.
  - Pointing **multiple** repos at the same absolute path **silently collides**
    them into one graph (no per-repo namespacing).
  - There is **no read-only consumer mode** — every `ckg` open assumes it may
    write (`.ckg/meta.json`, `dirty.json`, temporal db).
- The **server backends** (Neo4j/pgvector/SurrealDB) already centralize storage,
  but the same collision/namespacing question applies (which repo owns which
  records in a shared server?), and there's no documented "central build → many
  read-only consumers" pattern.

## Proposed change

Three additive pieces — config, a tiny helper, and a consumer flag. **No
engine-core change; no migration.**

### 1. A central store root with auto per-repo subdir

Add an optional `store.root` (or reuse `store.path` semantics) such that when a
**central root** is configured, the engine derives a **stable per-repo subdir**
instead of writing to the root directly:

```yaml
# agentforge.yaml  (app: passthrough)  — or standalone ckg.yaml
app:
  store:
    central_root: ~/.agentforge/ckg     # absolute → central hosting
    # path: .ckg                        # (default) in-repo when central_root unset
```

Resolution becomes:

- `central_root` **unset** → today's behavior: `root = repo_path / store.path`
  (in-repo `.ckg`). **Zero behavior change** for existing users.
- `central_root` **set** → `root = central_root / <repo-key>`, where `<repo-key>`
  is a stable slug derived from the repo (e.g. git remote URL → `org/repo`, else
  the absolute repo path hashed). This is the one new helper:
  `store.location.repo_key(repo_path) -> str`. Embedded Kuzu/LanceDB get a
  distinct dir per repo; server backends get a distinct **namespace/db/table
  prefix** keyed the same way.

This makes "centralize all three repos under one parent" a one-line config that
**cannot collide**.

### 2. Read-only consumer mode

Add `--read-only` (and `store.read_only: true`) so a developer/agent/CI consumer
opens a **central** index without ever writing manifests or attempting a refresh:

- Skips `meta.json`/`dirty.json`/temporal writes.
- `ckg index`/`enrich` refuse in read-only mode with a clear message.
- `ckg query`/`map`/`routes`/`serve-mcp` work normally, read-only.

This is what lets a team host the graph and hand a connection string to N
consumers safely.

### 3. Documentation: the three deployment shapes

A guide section (extend `09-storage-backends.md` or a new
`11-deployment-topologies.md`) that states the choice plainly:

| Shape | Config | Who builds | Who reads |
|---|---|---|---|
| **Laptop** (default) | `store.path: .ckg` | the dev | the dev |
| **Central, embedded** | `store.central_root: /shared/ckg` | a team/CI | many, `--read-only` |
| **Central, server** | `store.driver: surrealdb` (or neo4j/pgvector) + central host | a team/CI | many, `--read-only` |

## Implementation sketch

Grounded in `store/facade.py` and `config.py`:

- `StoreConfig` gains `central_root: str | None` and `read_only: bool` (default
  off / False → no behavior change).
- New `store/location.py`: `resolve_root(repo_path, cfg) -> Path | ServerNamespace`
  and `repo_key(repo_path) -> str` (git-remote-derived, path-hash fallback). This
  is the *only* new logic; `facade.open` calls it instead of the inline
  `Path(repo_path) / cfg.path`.
- For server backends, thread `repo_key` as a namespace/prefix into the
  Neo4j/pgvector/SurrealDB adapters (they already take a `config`).
- `read_only` threads to the incremental layer (skip `IndexMeta`/`DirtySet`
  writes) and gates write CLI verbs.

## Surfaces

- `ckg index --central-root <dir>` / `store.central_root` config.
- `ckg <verb> --read-only` / `store.read_only`.
- `ckg status` prints the resolved store location + `read_only` + `repo_key`.
- Guide: deployment topologies table.

## Suggested chunk plan (one branch, multiple commits)

1. `store/location.py` (`repo_key` + `resolve_root`) + `StoreConfig.central_root`;
   wire `facade.open`; tests for in-repo (unchanged) vs central (subdir, no
   collision across two repos).
2. `read_only` config + flag; gate write verbs; skip meta/dirty/temporal writes;
   tests.
3. Server-backend namespacing (`repo_key` → Neo4j db / pgvector schema /
   SurrealDB ns-db); conformance still green.
4. Deployment-topologies guide + `ckg status` location line.

## Acceptance criteria

- Two different repos with the same `central_root` produce **separate** graphs
  (no collision), each queryable.
- `--read-only` consumer can `query`/`map`/`serve-mcp` a central index and is
  refused on `index`/`enrich`.
- Default (no `central_root`) is **byte-for-byte** today's behavior.
- Conformance suites unchanged for all backends.

## Notes / alternatives / risks

| Concern | Note |
|---|---|
| `repo_key` stability | Prefer git remote (`org/repo`) so the key is host-independent; fall back to a hash of the canonical path. Document that a repo with no remote keys by path. |
| Concurrent writers to a central store | Out of scope here (named in the THEME) — this enh enables a central store and read-only consumers; coordinating multiple writers is follow-on ops. |
| Absolute `store.path` already works | Yes — this formalizes + namespaces it and adds the consumer safety mode, rather than leaving it as folklore. |

## 0.4.x / 0.5 candidacy

Strong near-term candidate: small, additive, no migration, and it's the
**prerequisite rung** for ENH-020 federation (which addresses central stores).
Ship independently of ENH-019.
