# Runbook — cross-file framework resolution (ENH-011)

> **Goal:** understand, operate, and debug the pass-2 that composes router
> prefixes across files and grounds DI providers to their definitions.
> **Applies to:** FastAPI today; Flask / Express / Django reuse the same rail.
> **Relates to:** [framework-extraction.md](framework-extraction.md),
> `docs/enhancements/ENH-011-cross-file-framework-resolution.md`.

## What it does

The intra-file packs (feat-011) extract a `Route`/`Service` and its handler in
the file where they appear. Real apps split the rest across files — a router is
declared in one module and mounted with a prefix in another; a DI provider is
defined in one module and injected in another. ENH-011 stitches those
compose-points in a second pass.

| Input (as written) | Output |
|---|---|
| `payments/routes.py`: `@router.get("/charge")` | `Route` base `path=/charge`, `router_var=router` |
| `main.py`: `app.include_router(payments.router, prefix="/api")` | `RouteMount` marker (`router_ref`, `prefix`) |
| → pass-2 | route `path_pattern = /api/charge` (base `path` unchanged) |
| `db.py`: `def get_db(): …` + `main.py`: `Depends(get_db)` | `PROVIDED_BY` edge `Service → get_db`, `Service.provider_symbol` set |

## How it works (the two passes)

**Pass-1 (per-pack, file-isolated).** Each route records the `@app`/`@router`
object it hangs off (`router_var`) and a `path_pattern` initialised to the base
`path`. Each `include_router(...)` becomes a `RouteMount` marker **node owned by
the mounting file** — so it rides feat-004 incrementality (cleared and
re-emitted when that file is re-parsed).

**Pass-2 (generic, cross-file).** `frameworks/cross_file.py` runs after the
language resolver (so `IMPORTS` edges exist) on every full **and** incremental
index. It reads **only the persisted graph**:

1. **Route prefixes.** For each `RouteMount` in file *F*: find routes whose
   `router_var` matches the mounted router, in a file *F* imports (or *F*
   itself). Recompute every route's `path_pattern` from its immutable base
   `path` + the matched prefix.
2. **DI grounding.** For each `Service`, resolve its `provider` name to a
   `Function`/`Method`/`Class` in an imported file and emit `PROVIDED_BY`.
3. **Route-handler grounding.** For each `Route` carrying `handler_class` +
   `handler_method` (Laravel / Rails, whose DSL names the controller by string
   in a *different* file), resolve `Class#method` anywhere in the repo (unique
   class match) and emit `HANDLED_BY`. Routes carrying `handler_class` never have
   a parsed `HANDLED_BY`, so clearing+rebuilding their edge is safe.

Both stages **recompute from scratch each run** (clear-and-rebuild), so an
incremental re-index converges to the exact graph a full index would produce
(`incremental == full`). The base `path` is parsed ground truth and is **never**
mutated — only `path_pattern` is (re)written.

### Why it's conservative (ADR-0004)

Resolution is **unique-match-only**. A mount or provider is resolved only when
it maps to exactly one target. Ambiguity (two imported files expose the same
`router_var` and the ref's head doesn't disambiguate; a provider name matches
two symbols) or an external target leaves it **unresolved and counted** in
`framework_unresolved` — it is never guessed wrong.

## Operate it

```bash
ckg index .          # full index (runs pass-2)
ckg routes .         # shows composed path_pattern, annotates the base path:
                     #   GET   /api/charge   →  charge  (payments/routes.py:6)  [base /charge]
```

Counts land in the `IndexReport`:

```python
from agentforge_graph.ingest import CodeGraph
cg = await CodeGraph.index(repo_path=".")
s = cg.stats()
s.route_prefixes_composed   # routes that gained a prefix
s.di_providers_grounded     # PROVIDED_BY edges emitted
s.framework_unresolved      # mounts/providers seen but ambiguous/external
```

Over MCP, `ckg_routes` returns `path_pattern` in each row, and its `path` filter
matches the composed URL (`{"path": "/api/users"}` finds a prefixed route).

## Troubleshoot

**A route prefix isn't applied (`path_pattern == path`).**
1. Is the mount recognised? `RouteMount` nodes should exist:
   ```python
   from agentforge_graph.core import GraphQuery, NodeKind
   mounts = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.ROUTE_MOUNT], limit=999))).nodes
   ```
   No marker → the `include_router(...)` call had a non-literal router ref or
   prefix (counted in `framework_unresolved`). Only string-literal prefixes and
   identifier/attribute router refs are resolved.
2. Is there an `IMPORTS` edge from the mounting file to the router's file? Pass-2
   only looks in imported files (plus the mount's own file). If the language
   resolver didn't link the import, the mount can't find its routes:
   ```python
   from agentforge_graph.core import EdgeKind, SymbolID
   mf = SymbolID.parse(mount.id); fid = SymbolID.for_symbol(mf.lang, mf.repo, mf.path, "")
   await cg.store.graph.adjacent(fid, [EdgeKind.IMPORTS], direction="out")
   ```
3. Does the route's `router_var` match the mount's `router_var` (the last
   segment of `router_ref`)? A router renamed on import won't match (conservative
   — left unresolved).
4. Two files expose the same router variable and the ref is bare (`router`, not
   `pkg.router`)? Ambiguous → unresolved by design. Use a qualified ref.

**A DI provider isn't grounded (no `PROVIDED_BY`, `provider_symbol` unset).**
- The provider must resolve to **exactly one** in-repo `Function`/`Method`/
  `Class` reachable via the consumer file's imports. A third-party provider
  (e.g. from a library) stays ungrounded by design. A name colliding across two
  imported modules is ambiguous → unresolved.

**Incremental and full disagree.** They shouldn't — pass-2 is global
clear-and-rebuild. If you see drift, confirm the `RouteMount`/`Service` nodes are
file-owned (their id path is the source file) and that `frameworks.resolve` ran
(it runs whenever any framework pack is active). File a bug with the repo state.

## Extending to another framework

The pass-2 stitch is **framework-agnostic** — it keys off `RouteMount` +
`router_var` + `Service.provider`, not off FastAPI specifics. To add Flask /
Express / Django, only **pass-1 capture** changes in that pack:

1. Tag each route with `router_var` (the app/blueprint/router object).
2. Emit a `RouteMount` node for the mount call (`register_blueprint(bp,
   url_prefix=…)`, `app.use('/p', router)`, `urls.py` `path(...)`), with
   `router_ref` / `router_var` / `prefix` attrs, owned by the mounting file.

No pass-2 changes are needed — the generic stitch picks them up.
