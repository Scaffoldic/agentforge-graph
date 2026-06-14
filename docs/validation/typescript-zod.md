# colinhacks/zod (TypeScript) — validation run

Second W1 run, first TypeScript: a real, widely-used TS library (schema
validation), `src/`-layout, extensionless relative imports, generics-heavy
class hierarchy rooted at an **abstract** base.

- **repo:** https://github.com/colinhacks/zod @ `v3.23.8`
- **date:** 2026-06-14
- **pipeline:** index ✅ · embed ⬜ (no live embedder creds) · enrich ⬜
- **command:** `ckg index /tmp/zod` (default config)

## Counts

```
indexed 170 files: 804 nodes, 1220 edges
  nodes: File=170, Class=86, Function=132, Method=416
  edges: CALLS=332, CONTAINS=634, IMPORTS=254
  imports: 131 in-repo resolved + 123 external
  calls:   332 resolved (272 same-file, 60 cross-file) / 14047 unresolved
```

> **Note:** zod ships both `src/` **and** a `deno/lib/` mirror of the same
> sources, so the graph contains everything twice (`src/types.ts` and
> `deno/lib/types.ts` both present). The tool did the right thing — the repo
> duplicates its source; a consumer would set `ingest.exclude` to one tree.

## Scores

| Dimension | Result | Verdict |
|---|---|---|
| **Parse coverage** | 170/170 files parsed, 0 skipped | ✅ excellent |
| **Import resolution** | **131 in-repo resolved** — extensionless relative imports (`./helpers/util`, `./errors`) resolve cross-file via the TS path mechanism | ✅ good (the BUG-004 analog is healthy on TS) |
| **Symbol extraction — concrete** | `ZodString`/`ZodObject`/`ZodArray`/`ZodError`/`ZodNumber`/`ParseStatus` all present | ✅ good |
| **Symbol extraction — abstract** | was MISSING; **BUG-005 fixed this run** — `ZodType` now extracts as a Class with its 32 methods (Class 86→92, Method 416→482) | ✅ fixed (BUG-005) |
| **Symbol extraction — enums/consts/types** | `ZodIssueCode`, `ZodFirstPartyTypeKind`, `ZodParsedType` MISSING (enums / const objects / type aliases not captured); arrow-`const` functions not captured | ⚠️ **ENH-008** (completeness) |
| **Call resolution** | 332 resolved (272 same-file, 60 cross-file) — cross-file works; low overall rate dominated by external + method-chain calls (expected), worsened by BUG-005 dropping `ZodType`'s methods | ⚠️ partial |
| **Repo-map / routes / decisions** | n/a (library, no web routes / ADRs) | ✅ |
| **Retrieval / enrichment / MCP** | not run — no live model creds in this env | ⬜ pending |

## Findings

- **[BUG-005](../bugs/BUG-005-typescript-abstract-class-not-extracted.md)** ✅
  **fixed this run** — the TS pack missed `abstract class` declarations
  (`abstract_class_declaration` not matched). Added the pattern; `ZodType` now
  extracts with its 32 methods (Class 86→92, Method 416→482). High value: it's the
  root every `Zod*` schema extends.
- **[ENH-008](../enhancements/ENH-008-typescript-symbol-completeness.md)** —
  broaden TS/JS extraction to `interface`, `enum`, `type` aliases, and
  arrow/`const`-assigned functions. These are pervasive in real TS (zod exposes
  much of its surface as enums/const objects + arrow helpers); structure-only
  classes+functions under-represents the codebase.

## What this run validated

- **TS parsing + relative-import resolution are solid** — the path-based import
  mechanism resolves real extensionless imports cross-file (the TS counterpart to
  the Python BUG-004 fix is healthy).
- **The first TS extraction gaps are about *what counts as a symbol*** — abstract
  classes (a bug) and the broader TS vocabulary (enums/interfaces/type-aliases/
  arrow-consts, an enhancement). Concrete classes, functions, and methods extract
  cleanly.

## Next

1. ✅ **BUG-005 fixed** (this run) — `ZodType` + its 32 methods now extract.
2. Scope **ENH-008** (TS/JS symbol vocabulary: interfaces/enums/types/arrow-consts).
3. A JavaScript run, and a creds-enabled pass for retrieval/enrichment/MCP.
