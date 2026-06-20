# Framework extraction — routes, ORM models, DI as graph edges

A plain symbol graph shows calls and imports. A web app's *real* architecture —
`POST /payments` → handler → `Payment` model — is wired through decorators, ORM
metaclasses, and DI containers. **agentforge-graph extracts that wiring as graph
edges an agent can traverse** (feat-011).

## What's extracted, per framework

| Framework | Language | Extracts |
|---|---|---|
| **FastAPI** | Python | routes (`@app.get`), **DI** (`Depends`/`Security`), class-based handlers |
| **Flask** | Python | routes (`@app.route(..., methods=[…])`, blueprints, 2.0 shortcuts) |
| **SQLAlchemy** | Python | ORM models (`DataModel`), columns (`HAS_FIELD`), relationships/FKs (`RELATES_TO`) |
| **Django** | Python | ORM models (`models.Model`), FK/O2O/M2M (`RELATES_TO`) |
| **Express** | JS/TS | routes (`app.get('/x', handler)`) |
| **NestJS** | TS | controller routes (`@Controller` + `@Get`/`@Post`/…) |
| **Spring** | Java | controller routes (`@RestController` + `@GetMapping`/…) |
| **Gin** | Go | routes (`r.GET('/x', handler)` — method-call, named handler → `HANDLED_BY`) |
| **ASP.NET** | C# | controller routes (`[HttpGet("/x")]` attributes, `[controller]` token, `[Route]` base) |
| **Laravel** | PHP | routes (`Route::get('/x', [C::class, 'm'])`) — controller grounded cross-file |
| **Rails** | Ruby | routes (`routes.rb` explicit `get '/x' => 'c#a'` / `to:` / `root`) — controller grounded cross-file |

**New nodes:** `Route`, `DataModel`, `Service`. **New edges:** `HANDLED_BY`
(Route→handler), `HAS_FIELD` (DataModel→column), `RELATES_TO` (DataModel↔DataModel),
`INJECTED_INTO` (Service→consumer).

## Use it

Framework packs **auto-activate** when their dependency is detected — no config
needed. Just index, then ask:

```bash
ckg index .

ckg routes        # METHOD PATH → handler (file:line)
ckg models        # table, fields, and relations (fk / o2o / m2m / relationship)
ckg services      # provider → the functions it's injected into
```

```text
$ ckg models
users [users]  (app/models.py:7)
    fields: id, name, email
    relations: posts→posts (relationship)
posts [posts]  (app/models.py:18)
    fields: id, title, author_id
    relations: author_id→users (fk)
```

Over **MCP**, the `ckg_routes` tool returns the same as JSON (method/path/handler);
ORM models and DI surface through graph expansion on `ckg_search`/`ckg_neighbors`
(a hit on a handler reaches its `Route`, and a model reaches its `RELATES_TO`
neighbours).

## Configure

```yaml
# ckg.yaml
frameworks:
  enabled: auto          # auto-detect per repo (default) | off | an explicit list
  packs: []              # force-enable, e.g. ["fastapi", "sqlalchemy"]
```

## How resolution stays honest

- A class becomes a `DataModel` only with **declarative evidence** (a
  `__tablename__`/`models.Model` base or real columns) — plain classes never
  become false models (ADR-0004).
- A route handler resolves to the **real** symbol (`HANDLED_BY` lands on the
  actual function/method node, verified end-to-end). An anonymous Express handler
  still yields the `Route` (the API surface) with no edge.
- Cross-file `RELATES_TO` (SQLAlchemy `relationship("X")` / Django FK targets) is
  stitched in a globally-idempotent pass-2, so an incremental re-index converges
  to the full-index graph.

## Cross-file resolution (ENH-011)

Real apps split routers and providers across files. A globally-idempotent pass-2
(`frameworks/cross_file.py`) stitches those compose-points using only the
persisted graph (`IMPORTS` edges + node attrs), unique-match-only:

- **Route-prefix composition** — `app.include_router(payments.router,
  prefix="/api")` composes `/api` onto the included router's routes. The base
  `path` stays as written; the composed URL lands in **`path_pattern`** (equal to
  `path` for an unmounted route). `ckg routes` shows the composed path and
  annotates the base.
- **DI grounding** — a `Depends(get_db)` provider name resolves to the
  `get_db` **function symbol** in the imported module, emitting a traversable
  `PROVIDED_BY` edge (so "what provides this dependency" crosses files).
- **Route-handler grounding** — a route whose DSL names its handler by string
  (Laravel `[C::class, 'm']` / `'C@m'`, Rails `'controller#action'`) records the
  controller + action; pass-2 grounds them to the real `Class#method` symbol
  anywhere in the repo (unique-match), emitting `HANDLED_BY` across files.

Ambiguous or external targets are left unresolved and counted in
`framework_unresolved`, never guessed. Operational detail + troubleshooting:
[cross-file-framework-resolution.md](cross-file-framework-resolution.md).

## Not yet (residuals)

Cross-file route prefixes + DI grounding ship for **FastAPI**; Flask
`register_blueprint`, Express `app.use('/p', router)` and Django `urls.py` reuse
the same pass-2 rail (per-pack pass-1 capture pending). Of the ENH-012 packs,
**routes** ship for Gin / ASP.NET / Laravel / Rails; their ORM models (EF Core,
Eloquent, ActiveRecord), the ASP.NET minimal API, and the Rails resourceful DSL
(`resources`) are follow-ups — see
[`docs/features/feat-011-framework-extractors.md`](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/features/feat-011-framework-extractors.md).
