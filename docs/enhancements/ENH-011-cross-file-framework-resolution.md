# ENH-011: cross-file framework resolution (route prefixes + DI grounding)

| Field | Value |
|---|---|
| **ID** | ENH-011 |
| **Value/Impact** | Med–High (completes the route/DI graph for real, multi-file apps) |
| **Effort** | M |
| **Status** | **in progress · 0.4.0** — FastAPI route prefixes + DI grounding shipped; Flask/Express/Django pass-1 pending |
| **Area** | `frameworks` (pass-2 `resolve`) |
| **Relates to** | feat-011 (framework extractors), feat-004 (incremental) |

> **Implemented (FastAPI):** generic pass-2 `frameworks/cross_file.py` —
> route-prefix composition (`RouteMount` markers + `path_pattern`) and DI
> grounding (`PROVIDED_BY`). Runbook:
> [`docs/guides/04-cross-file-framework-resolution.md`](../guides/04-cross-file-framework-resolution.md).
> Remaining: Flask/Express/Django pass-1 capture, nested-mount fixed-point.

## Motivation

feat-011 extracts routes and DI **intra-file**: a `Route` and its handler, a
`Service` and its consumer, both live in one file. Real apps split this across
files — routers are composed with prefixes, views are referenced by string, and
DI providers are imported. Today those compose-points are **counted, not
resolved**:

- FastAPI `app.include_router(payments.router, prefix="/api")` → the routes on
  `payments.router` should get the `/api` prefix in their final `path_pattern`.
- Flask `app.register_blueprint(bp, url_prefix="/api")`; Express
  `app.use('/api', router)` — same shape.
- Django `urls.py` `path("users/", views.user_list)` — string/attr view refs.
- DI: `Depends(get_db)` records the provider **name**; it isn't grounded to the
  `get_db` **function symbol** when that provider is imported from another module.

## Analysis — what exists vs what's missing

- The framework **pass-2 hook** (`FrameworkPack.resolve` / `FrameworkExtractor.
  resolve`) is already wired into the full pipeline + incremental indexer (it's
  what ORM `RELATES_TO` uses) and is **globally idempotent**. So the machinery to
  do cross-file stitching exists.
- **Missing (pass-1):** record per route the **router variable** it's attached to;
  record `include_router`/`use`/`register_blueprint` facts (the included router +
  prefix). Record DI provider names already happens.
- **Missing (pass-2):** resolve the included router reference to the file that
  defines it (needs the language resolver's **import bindings**, which the
  framework pass-2 doesn't currently see), then compose the prefix onto that
  file's router-scoped routes; for DI, resolve the provider name to its in-repo
  function symbol the same way.

## Proposed approach

1. Pass-1: tag each `Route` with `attrs.router_var`; emit `include`/`mount`
   markers (router ref + prefix) on the file node or a transient fact.
2. Give the framework pass-2 read access to import bindings (expose a minimal
   "what does name X in file F import" lookup from the resolver, or re-derive
   from `IMPORTS` edges + export maps).
3. Compose prefixes onto the target file's router-scoped routes; ground DI
   providers to their symbol. **Unique-match-only** (ADR-0004) — ambiguous or
   external refs stay unresolved, reported in `framework_unresolved`.
4. Keep it globally idempotent so incremental == full.

## Implementation sketch (data shapes)

Grounded in the code as it stands (`frameworks/base.py`, `extractor.py`,
`packs/fastapi/__init__.py`, `orm.py`, `ingest/resolver.py`). Two new pass-1
facts, one reused pass-2 rail.

### Pass-1 — record, never compose (file-isolated)

**Route base path is immutable; the composed path is a separate attr.** Today a
`Route` node carries `attrs = {method, path, framework, handler}`. Add two:

- `attrs.router_var` — the decorator's *object* name (`@app.get` → `"app"`,
  `@router.post` → `"router"`). Captured from the decorator call's `object`
  field in `_extract_routes`. This is how pass-2 knows which routes a given
  mount applies to.
- `attrs.path_pattern` — initialised equal to `attrs.path`. **Parsed `path` is
  never mutated**; pass-2 only ever (re)writes `path_pattern`. So a full
  re-index and an incremental resolve land on the same value (feat-004).

**Mount markers ride the mounting file's FileSubgraph as nodes.** A
`app.include_router(payments.router, prefix="/api")` lives in `main.py`, which
may contain *zero* routes — so the fact must be file-scoped to `main.py`, not
hung off a route. Mirror the existing "facts as nodes merged into the
FileSubgraph" pattern: emit a transient marker node (proposed
`NodeKind.ROUTE_MOUNT`) from `extract()`, `origin_path = main.py`, so it rides
feat-004 incrementality and is cleared when `main.py` is re-parsed:

```python
Node(
    id=SymbolID.for_symbol(slug, repo, file.path, f"mount({router_ref}@{lineno})."),
    kind=NodeKind.ROUTE_MOUNT,
    attrs={
        "framework": "fastapi",
        "router_ref": "payments.router",  # as written at the call site
        "prefix": "/api",                  # "" when absent
    },
    provenance=prov,  # parsed
)
```

Flask `register_blueprint(bp, url_prefix=…)`, Express `app.use('/api', router)`,
Django `urls.py` `path("users/", views.user_list)` all reduce to the same
`(router_ref, prefix)` marker — only the query capture differs per pack.

**DI grounding needs nothing new in pass-1** — the `Service` node already
carries `attrs.provider` (the name) and the `INJECTED_INTO` edge. Pass-2 grounds
the name to a symbol.

### Pass-2 — `resolve(store, commit)` (cross-file, globally idempotent)

Extend the existing `FrameworkExtractor.resolve` (which today only clears+rebuilds
`RELATES_TO`). Add a route-prefix stitch and a DI-grounding stitch, both pure
functions of the persisted graph:

1. **Recompute every route's `path_pattern` from scratch each run** (the
   `RELATES_TO` global-clear discipline, applied to an attr):
   - Load all `ROUTE_MOUNT` + `ROUTE` nodes.
   - For each mount in file `F`: split `router_ref` into `(module_alias, attr)`
     (`payments`, `router`). Resolve `module_alias` → target file via **`F`'s
     persisted `IMPORTS` edges + its `imports` node attrs** (the same
     module-alias map the resolver builds at `resolver.py:193`+; re-derived from
     the graph, not the resolver's transient `bindings`). Unique match only.
   - In the target file, select routes whose `attrs.router_var == attr` and set
     `path_pattern = join(prefix, path)`. Chained includes compose
     (router→router→app) by iterating to a fixed point.
   - Write via `store.set_attrs` (or upsert) — idempotent; routes with no
     applicable mount keep `path_pattern == path`.
2. **Ground DI providers.** For each `Service`, resolve `attrs.provider` →
   in-repo `Function` symbol via the consumer file's IMPORTS map (unique match),
   then emit a new traversable edge (proposed `EdgeKind.PROVIDED_BY`,
   `Service → Function`) and stamp `attrs.provider_symbol`. External/ambiguous →
   unresolved.

The module-alias re-derivation is the one genuinely new helper; everything else
is the proven clear-and-rebuild rail. Both `NodeKind.ROUTE_MOUNT` and
`EdgeKind.PROVIDED_BY` are **additive enum values** — no index migration
(ADR-0006 only rebuilds on schema *mismatch*; new kinds are forward-compatible on
the schemaless/edge-table backends).

### Surfaces

- `CodeGraph.routes()` / `ckg routes` show the **composed** `path_pattern` (fall
  back to `path` when unmounted); add a `--raw` to show base paths.
- `ModelInfo`-style: `RouteInfo.path_pattern`, `RouteInfo.mounted_under`.
- `IndexReport`: `route_prefixes_composed`, `di_providers_grounded`,
  and unresolved counts folded into `framework_unresolved`.

### Suggested chunk plan (one feat branch, multiple commits)

1. `ROUTE_MOUNT` + `PROVIDED_BY` kinds, `router_var`/`path_pattern` on FastAPI
   routes, mount-marker emission (pass-1) + tests.
2. Pass-2 module-alias re-derivation helper (from IMPORTS + import attrs) +
   FastAPI prefix composition + `incremental == full` test.
3. DI grounding (`PROVIDED_BY`) for FastAPI.
4. Express `app.use` + Flask `register_blueprint` prefix composition (reuse the
   pass-2 rail; per-pack pass-1 capture only).
5. Django `urls.py` string/attr view refs.
6. Surfaces (`ckg routes` composed path, IndexReport counts, `--raw`).

## Risks

| Risk | Mitigation |
|---|---|
| Import-binding resolution is the hard part | Reuse the language resolver's existing module-alias/export maps; conservative unique-match |
| Multiple routers per file → ambiguous prefix attribution | Track which router each route is attached to (router_var) |
| Dynamic registration (loops) | Count + report, never guess |

## 0.4.0 candidacy

Good 0.4.0 candidate — high practical value (most FastAPI/Express apps split
routers across files), moderate effort, and the pass-2 rail already exists.
Could ship FastAPI + Express prefix composition first; Django `urls.py` and DI
grounding as follow-ons.
