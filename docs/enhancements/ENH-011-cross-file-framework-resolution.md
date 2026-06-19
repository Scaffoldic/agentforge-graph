# ENH-011: cross-file framework resolution (route prefixes + DI grounding)

| Field | Value |
|---|---|
| **ID** | ENH-011 |
| **Value/Impact** | Med–High (completes the route/DI graph for real, multi-file apps) |
| **Effort** | M |
| **Status** | proposed (0.4.0 candidate) |
| **Area** | `frameworks` (pass-2 `resolve`) |
| **Relates to** | feat-011 (framework extractors), feat-004 (incremental) |

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
