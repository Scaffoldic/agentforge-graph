# ENH-012: additional framework packs (Rails, Laravel, Gin, ASP.NET)

| Field | Value |
|---|---|
| **ID** | ENH-012 |
| **Value/Impact** | Med (cross-language parity for the framework differentiator) |
| **Effort** | M–L (per pack; one PR each) |
| **Status** | **routes shipped · 0.4.0** — Gin, ASP.NET, Laravel, Rails routes done; ORM models + Rails `resources` are follow-ups |
| **Area** | `frameworks.packs` |
| **Relates to** | feat-011 (framework extractors), feat-002 (10 language packs) |

> **Implemented (routes, all four):** `frameworks/packs/{gin,aspnet,laravel,rails}`
> on new `_go_ast` / `_csharp_ast` / `_php_ast` / `_ruby_ast` helpers — Gin
> (method-call, mirrors Express), ASP.NET (attributes, mirrors Spring), Laravel
> (`Route::` DSL), Rails (`routes.rb` explicit declarations). Laravel + Rails name
> their controller cross-file, so a **generic route-handler grounding** step was
> added to `frameworks/cross_file.py` (Route `handler_class`+`handler_method` →
> `Class#method`, unique-match, idempotent). Conservative throughout (ADR-0004).
> **Follow-ups:** ORM models (EF Core / Eloquent / ActiveRecord), ASP.NET minimal
> API, Rails resourceful `resources` DSL expansion.

## Motivation

feat-011 ships 7 packs across Python, JS/TS, and Java. The 10 v0.1 language packs
already unblock the rest of the popular web stack — only the framework packs are
missing. Extending coverage to Ruby/PHP/Go/C# makes "framework awareness" a
cross-language feature, not a Python-leaning one (cross-language parity §6).

## Analysis — per framework

| Framework | Lang | Routing style | ORM | Tractability |
|---|---|---|---|---|
| **Gin / Echo** | Go | `r.GET("/x", handler)` — method-call (like Express) | — | **Easy** — mirror the Express pack; named handler → `HANDLED_BY` |
| **ASP.NET** | C# | `[HttpGet("/x")]` attributes on controller methods, **or** minimal API `app.MapGet("/x", …)` | EF Core (`DbSet<T>`, `[Table]`) | **Med** — attribute style mirrors Spring; minimal API mirrors Express |
| **Laravel** | PHP | `Route::get('/x', [C::class, 'm'])` — static-call DSL | Eloquent (`class X extends Model`) | **Med** — method-call DSL + Eloquent models mirror the ORM rails |
| **Rails** | Ruby | `routes.rb` config DSL (`resources :users`, `get '/x' => 'c#m'`) | ActiveRecord (`class X < ApplicationRecord`, `has_many`) | **Harder** — routing is a config DSL, not annotations; needs a dedicated `routes.rb` interpreter |

- **Routes** ride the existing route helpers (the shared `_js_ast`-style approach
  generalises; Go/C#/Ruby/PHP each get a small AST-helper module like
  `_python_ast`/`_js_ast`).
- **ORM** (Eloquent, ActiveRecord, EF Core) rides `frameworks/orm.py` (`ModelIndex`
  + `relations_to_edges`) exactly like SQLAlchemy/Django.

## Proposed approach

One pack per framework, one PR each, on the existing rails. Suggested order by
value/effort: **Gin** (easiest, mirrors Express) → **ASP.NET** (attributes mirror
Spring) → **Laravel** (routes + Eloquent) → **Rails** (the `routes.rb` DSL is the
real work). Each: detection (deps/imports), a routes/ORM `.scm` + extractor,
golden + e2e tests asserting `HANDLED_BY`/`RELATES_TO` land on real symbols.

## Risks

| Risk | Mitigation |
|---|---|
| Rails `routes.rb` is config-DSL, not declarations on the handler | Treat as a dedicated mini-interpreter; ship Rails **last**, or scope to explicit `get/post '…' => 'c#m'` first |
| Per-language AST-helper duplication | Factor a small `_<lang>_ast` per language, mirroring `_python_ast`/`_js_ast` |
| Resolver completeness varies per pack (BUG-006 history) | Conservative unique-match; count unresolved |

## 0.4.0 candidacy

Partial — **Gin + ASP.NET** are strong 0.4.0 candidates (low effort, high parity
value). Laravel + Rails are better as a 0.5 batch given the per-language ramp and
the Rails DSL outlier.
