# serde-rs/json (Rust) — validation run

W3 run, Rust (10th and final pack) — completes the 10-language v0.1 scope. A real,
ubiquitous JSON crate; `src/`-layout, modules, traits, `impl` blocks,
`use crate::…` paths.

- **repo:** https://github.com/serde-rs/json @ `v1.0.108`
- **date:** 2026-06-15
- **pipeline:** index ✅ · embed ⬜ · enrich ⬜ (structural validation)
- **command:** `ckg index /tmp/serde_json --include 'src/**'`

## Counts

```
indexed 39 files: 1624 nodes, 2298 edges
  nodes: Class=197, Interface=17, Method=438, Function=614, TypeAlias=193, Variable=126, File=39
  edges: CALLS=608, CONTAINS=1585, IMPORTS=105
  imports: 19 in-repo + 86 external
  calls:   608 resolved / 1520 unresolved
```

## Scores

| Dimension | Result | Verdict |
|---|---|---|
| **Parse coverage** | 39/39 `src/` files parsed, 0 skipped | ✅ excellent |
| **Symbol extraction** | 197 structs/enums/unions/impls (`Value`/`Map`/`Number`→Class), 17 traits (→Interface), 438 methods, 614 functions, 193 type aliases, 126 const/static | ✅ strong |
| **Import resolution (path-derived)** | **19 in-repo** `use crate::a::b::Item` resolve via the file-derived module path (`src/a/b.rs` → `a::b`, `crate::` stripped); 86 external (`std::`, `serde::`) | ✅ works (single `use`; grouped/glob = follow-up) |
| **Call resolution** | **608 resolved** — free functions + items bound from `use crate::…` resolve cross-file; method/`x.f()`/`T::f()` calls stay unresolved (ADR-0004) | ✅ strong |
| **Routes / decisions** | none (a library) — correctly empty | ✅ n/a |
| **Retrieval / enrichment / MCP** | not run this pass | ⬜ pending |

## What this run validated

- **Path-derived module resolution works** — Rust's module path is implicit in the
  file layout, so the pack derives each file's module from its path
  (`namespace_from_path`) and resolves `use crate::shapes::Shape` to the file
  declaring `Shape` (FQN-style, `crate::` stripped). 608 calls resolve — the
  highest of the namespace-family packs, because `use crate::…` binds items.
- **`impl` blocks attach methods to their type** — `impl Circle { fn area(&self) }`
  merges with the `Circle` struct node, so methods nest under the type as
  `Method`s. Traits map to `Interface`.
- **Symbol extraction is comprehensive** — structs, enums, unions, traits, impls,
  functions, methods, const/static, and type aliases.

## Findings

- No correctness bug. Follow-ups (not blockers):
  - **Grouped/glob `use`** (`use crate::{a, b}`, `use crate::x::*`) isn't captured
    — only single-path `use a::b::Item`; this is why in-repo imports (19) under-
    count real coupling. A query extension.
  - **Generic `impl<T> Foo<T>`** (type is a generic, not a plain `type_identifier`)
    doesn't attach its methods to the type. Inline `mod` items aren't namespaced.
  - `self::`/`super::` relative paths and method-call resolution = follow-ups /
    the ADR-0004 boundary.

## Next

1. ✅ **Rust pack shipped + validated on serde_json** — **W3 complete: 10/10
   language packs ship** (the "10 languages" claim is now real).
2. Creds-enabled passes (embed + retrieval + enrich) across the new packs, and the
   remaining 0.1 hardening (ENH-004/005/009; W4 agent loop).
