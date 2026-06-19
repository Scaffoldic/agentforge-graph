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

## Not yet (residuals)

Cross-file route-prefix composition (`include_router(prefix=…)` / `app.use('/p',
router)` / Django `urls.py`), grounding DI provider names to their definitions,
and more frameworks (Rails, Laravel, Gin, ASP.NET) — see
[`docs/features/feat-011-framework-extractors.md`](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/features/feat-011-framework-extractors.md).
