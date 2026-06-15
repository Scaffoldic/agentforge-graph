# fmtlib/fmt (C++) — validation run

W3 run, C++ (9th pack, **Tier B** — structure + heuristic refs). A real, modern,
header-heavy C++ library (formatting).

- **repo:** https://github.com/fmtlib/fmt @ `10.2.1`
- **date:** 2026-06-15
- **pipeline:** index ✅ · embed ⬜ · enrich ⬜ (structural validation)
- **command:** `ckg index /tmp/fmt --include 'include/**' --include 'src/**'`

## Counts

```
indexed 16 files: 1072 nodes, 1378 edges
  nodes: Class=235, Function=579, Method=242, File=16
  edges: CALLS=294, CONTAINS=1056, IMPORTS=28
  imports: 17 in-repo + 11 external
  calls:   294 resolved / 1132 unresolved
```

## Scores

| Dimension | Result | Verdict |
|---|---|---|
| **Parse coverage** | 16/16 files parsed, 0 skipped (header-heavy: few, large files) | ✅ excellent |
| **Symbol extraction** | 235 classes/structs/enums, 579 free functions, 242 methods (in-class decls + out-of-line `Type::method` defs) | ✅ strong (Tier B) |
| **Include resolution** | **17 in-repo** — quoted `#include "fmt/format.h"` resolves relative to the file; `<system>` includes skipped (11 external were quoted-but-unmatched) | ✅ good |
| **Call resolution** | 294 resolved — free functions in a namespace resolve by name (namespaces are scopes, not member-access barriers in our model); `obj.m()`/`ns::f()` stay unresolved (ADR-0004) | ✅ partial |
| **Routes / decisions** | none — correctly empty | ✅ n/a |
| **Retrieval / enrichment / MCP** | not run this pass | ⬜ pending |

## What this run validated

- **Structure + heuristic refs (the Tier-B bar) work on real C++** — classes,
  structs, enums, free functions, in-class method declarations, and out-of-line
  `Type::method` definitions all extract; quoted includes form the dependency
  graph; namespace-local free-function calls resolve.
- **Honest Tier-B limits** (documented, not blockers):
  - **Template-heavy constructs** classify imperfectly — some template
    `struct`/`class` and deduction guides surface as `Function` rather than
    `Class` (e.g. `formatter`, `basic_format_args`). The symbol is present and
    findable; the *kind* can be wrong on templates.
  - **Out-of-line method definitions** also appear as a file-scope `Function`
    (a slight duplicate of the in-class `Method`) — both are findable.
  - **Root-relative includes** (resolved via an include path, not file-relative)
    that don't match a file-relative path stay external.
  - Overload/template/`obj.method()` call resolution = the ADR-0004 boundary.

## Findings

- No correctness bug for the Tier-B scope. Template kind-classification and the
  out-of-line-def duplicate are the notable follow-ups.

## Next

1. ✅ **C++ pack shipped + validated on fmt** (this run).
2. Continue W3: **Rust** (Tier A) — the last pack to complete the 10-language scope.
