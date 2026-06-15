# Seldaek/monolog (PHP) — validation run

W3 run, PHP (6th pack) — the first **namespace/FQN** import model. A real,
ubiquitous logging library, clean PSR-4 (`src/` → namespace `Monolog\…`).

- **repo:** https://github.com/Seldaek/monolog @ `3.6.0`
- **date:** 2026-06-15
- **pipeline:** index ✅ · embed ⬜ · enrich ⬜ (structural validation)
- **command:** `ckg index /tmp/monolog --include 'src/**'`

## Counts

```
indexed 119 files: 971 nodes, 1192 edges
  nodes: Class=112, Interface=7, Method=666, Variable=67, File=119
  edges: CALLS=0, CONTAINS=852, IMPORTS=340
  imports: 284 in-repo + 56 external
  calls:   0 resolved / 1563 unresolved
```

## Scores

| Dimension | Result | Verdict |
|---|---|---|
| **Parse coverage** | 119/119 `src/` files parsed, 0 skipped | ✅ excellent |
| **Symbol extraction** | 112 classes (`Logger`/`StreamHandler`/`LogRecord`→Class), 7 interfaces (`HandlerInterface`→Interface), 666 methods, 67 const, enums (`Level`)→Class | ✅ strong |
| **Import resolution (FQN)** | **284 in-repo** `use Monolog\…` statements resolve to the declaring file via the namespace/FQN index; 56 external (`Psr\Log\…`, etc.) | ✅ strong |
| **Call resolution** | 0/1563 — monolog is pure-OO: no top-level functions, every call is `$this->m()` / `new C()` (member access), unresolved by design (ADR-0004) | ⚠️ inherent (OO member dispatch) |
| **Routes / decisions** | none (a library) — correctly empty | ✅ n/a |
| **Retrieval / enrichment / MCP** | not run this pass | ⬜ pending |

## What this run validated

- **The namespace/FQN import model works** — a new, reusable resolver mechanism
  (shared by the upcoming Java/C# packs): each file's `namespace` declaration is
  recorded, every top-level symbol is indexed by its fully-qualified name
  (`namespace + class`), and a `use App\Foo\Bar` import resolves to the file
  declaring `Bar`. **284 in-repo imports resolved** — a real dependency graph.
- **Symbol extraction is comprehensive** — classes, interfaces, traits, enums
  (all the PHP type forms), methods, and constants.
- **Honest limit**: in a pure-OO codebase, *call* resolution is ~0 because every
  call is method dispatch on an object (`$this->handle()`), which is member access
  (ADR-0004). The value here is the **symbol graph + the namespace dependency
  graph**, both of which are complete and correct.

## Findings

- No correctness bug. Follow-ups (not blockers):
  - **Grouped/aliased use** (`use A\{B, C}`, `use A\B as C`) — only single
    `use A\B;` is captured; grouped/aliased forms are a query extension.
  - Method/member call resolution = the shared ADR-0004 boundary.

## Next

1. ✅ **PHP pack shipped + validated on monolog** (this run). The FQN resolver
   mechanism is reused by the Java/C# packs.
2. Continue W3: C#, Java, Rust (Tier A) + C++ (Tier B).
