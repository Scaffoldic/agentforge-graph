# rails/thor (Ruby) — validation run

W3 run, Ruby (5th pack). A real, widely-used CLI gem; `lib/`-layout, modules +
classes, `require_relative` between files.

- **repo:** https://github.com/rails/thor @ `v1.3.0`
- **date:** 2026-06-15
- **pipeline:** index ✅ · embed ⬜ · enrich ⬜ (structural validation)
- **command:** `ckg index /tmp/thor --include 'lib/**'`

## Counts

```
indexed 36 files: 624 nodes, 649 edges
  nodes: Class=97, File=36, Function=38, Method=394, Variable=59
  edges: CALLS=19, CONTAINS=588, IMPORTS=42
  imports: 42 in-repo + 0 external
  calls:   19 resolved / 1985 unresolved
```

## Scores

| Dimension | Result | Verdict |
|---|---|---|
| **Parse coverage** | 36/36 `lib/` files parsed, 0 skipped | ✅ excellent |
| **Symbol extraction** | 97 classes/modules (`Thor`/`Command`/`Options`/`Base`/`Actions`→Class), 394 methods (incl. `def self.x`), 38 free funcs, 59 constants (→Variable) | ✅ strong |
| **Import resolution** | **42 in-repo** — every `require_relative "thor/x"` (bare, file-relative) resolves; the wildcard semantics bind the required file's top-level defs | ✅ good |
| **Call resolution** | 19/2004 ≈ 1% — Ruby is dynamically dispatched: almost every call is `obj.method` (member access), which stays unresolved by design (ADR-0004). Bare same/required-file calls resolve | ⚠️ inherent (dynamic dispatch) |
| **Routes / decisions** | none (a CLI gem) — correctly empty | ✅ n/a |
| **Retrieval / enrichment / MCP** | not run this pass | ⬜ pending |

## What this run validated

- **Symbol extraction is strong on idiomatic Ruby** — modules and classes (both
  →Class), instance + singleton (`def self.`) methods, and constants all extract
  with correct nesting.
- **`require_relative` resolution works** via two pack-agnostic mechanisms: a
  `relative_bare` flag (a bare `require_relative "thor/command"` is file-relative,
  unlike a TS/JS bare specifier which is an npm package) and `wildcard_import` (a
  name-less require makes the target file's top-level defs callable — Ruby has no
  named-import syntax).
- **The honest limit is Ruby's dynamism**: method calls are runtime-dispatched
  `obj.method`, so call resolution is intentionally sparse (the member-access
  boundary shared by every pack). The symbol graph + `require_relative` dependency
  graph are the delivered value.

## Findings

- No correctness bug. Follow-ups (not blockers):
  - **Load-path `require "thor/x"`** (lib-root relative, not file-relative) isn't
    resolved — only `require_relative` is. Resolving load-path requires needs
    lib-root detection (a follow-up; many gems mix both styles).
  - Method/`send` dynamic dispatch is out of scope for static resolution.

## Next

1. ✅ **Ruby pack shipped + validated on thor** (this run).
2. Continue W3: the next Tier-A pack (PHP/C#/Java/Rust) + C++ (Tier B).
