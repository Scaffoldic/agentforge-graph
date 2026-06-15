# colinhacks/zod (TypeScript) — validation run

Second W1 run, first TypeScript: a real, widely-used TS library (schema
validation), `src/`-layout, extensionless relative imports, generics-heavy
class hierarchy rooted at an **abstract** base.

- **repo:** https://github.com/colinhacks/zod @ `v3.23.8`
- **date:** 2026-06-14 (index) · **2026-06-15 (creds-enabled re-run after ENH-007/008)**
- **pipeline:** index ✅ · embed ✅ · enrich ✅ (2026-06-15, live Bedrock)
- **command:** `ckg index /tmp/zod` (original) · `ckg index … --include 'src/**'`
  then `embed`/`enrich --all` (creds re-run; `src/`-only to skip the `deno/lib` mirror)

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
| **Symbol extraction — enums/consts/types** | was MISSING; **ENH-008 fixed (2026-06-15)** — `ZodFirstPartyTypeKind` now extracts (enum → Class), `ZodIssueCode`/`ZodParsedType` (type aliases → TypeAlias); src-only re-index now reports **Interface=57, TypeAlias=241, Variable=21** (all previously 0) | ✅ fixed (ENH-008) |
| **Call resolution** | 332 resolved (272 same-file, 60 cross-file) — cross-file works; low overall rate dominated by external + method-chain calls (expected), worsened by BUG-005 dropping `ZodType`'s methods | ⚠️ partial |
| **Repo-map / routes / decisions** | n/a (library, no web routes / ADRs). Map leads with the `types.ts` file summary then the public `Zod*` classes — good orientation | ✅ |
| **Retrieval** | **2/4 surgical, 4/4 topically-relevant** (live Cohere embed-v4, 1047 chunks) — `ZodObject._parse` hit exactly; others returned adjacent chunks. zod's giant `types.ts` + locale files make exact-symbol retrieval harder than click. See creds-run below | 🟡 good, not surgical |
| **Enrichment** | summaries accurate + symbol-grounded; **2 Factory tags** (`ZodRecord`/`ZodPipeline` static `create()`, 0.75) — precise (6 of 8 candidates rejected) | ✅ good |

## Creds-enabled re-run (2026-06-15, live AWS Bedrock, after ENH-007/008)

Re-indexed `src/` only (82 files; skips the `deno/lib` mirror), then embed +
enrich on live models. **Cost ≈ $0.09** (embed ~free; tags $0.012; summaries $0.073).

**Re-index counts (ENH-008 effect):**

```
indexed 82 files: 843 nodes, 1023 edges
  nodes: Class=55, File=82, Function=146, Interface=57, Method=241, TypeAlias=241, Variable=21
  edges: CALLS=136, CONTAINS=761, IMPORTS=126
  imports: 63 in-repo + 63 external
```

`Interface`, `TypeAlias`, and `Variable` went **0 → 57 / 241 / 21** — the TS type
surface that was invisible before ENH-008. The three named gaps are closed:
`ZodFirstPartyTypeKind` → Class (enum), `ZodIssueCode` / `ZodParsedType` →
TypeAlias (found via their companion `type X = …` alias, by design).

**Embeddings** — `ckg embed`: 1047 chunks across 52 files, dim 1024, ~38s. ✅

**Retrieval** — `ckg query`, 4 NL questions:

| Question | Top result | Verdict |
|---|---|---|
| "how is an object schema parsed against input" | `ZodObject._parse(input)` (types.ts) | ✅ exact |
| "how do I make a schema field optional or nullable" | `ZodObject.required()` showing `ZodOptional` handling | 🟡 adjacent |
| "how is a string schema validated" | `StringValidation` union (the validation vocabulary) | 🟡 adjacent |
| "how are validation errors represented and collected" | `locales/en.ts` issue-message formatting | 🟡 adjacent |

Honest read: retrieval surfaces **topically-correct code** every time, but is
**surgical only on the well-scoped question** (object parsing). zod concentrates
most of its surface in one 2800-line `types.ts` plus locale files, so chunk-level
semantic search lands "near" the answer more often than "on" it. Lower-signal
than click (4/4) — zod is a harder, denser target, not a tool regression.

**Enrichment — summaries** (82 files + repo): accurate and architecturally
grounded. The repo summary correctly frames zod around the **abstract `ZodType`
base** + concrete validators + the parse pipeline + error maps (the abstract base
is itself an ENH/BUG-005 dividend — it's now in the graph to summarize). File
summaries hedge appropriately ("likely", "presumably") on inferred behaviour. ✅

**Enrichment — pattern tags**: 8 candidates → 8 judged → **2 tagged** (Factory).
`ZodRecord` and `ZodPipeline` both tagged Factory at 0.75 — the judge correctly
keys on their static `create()` factory methods, and **rejected 6** other
candidates. Unlike click (0 tags), zod genuinely uses the factory idiom, and the
judge found it without false positives. ✅ precise.

## Findings

- **[ENH-008](../enhancements/ENH-008-typescript-symbol-completeness.md)** ✅
  **done (2026-06-15)** — verified here: `Interface`/`TypeAlias`/`Variable` went
  0 → 57/241/21 on zod `src/`, and the three named missing symbols are now
  extracted. The TS surface is no longer under-represented.
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

1. ✅ **BUG-005 fixed** (2026-06-14) — `ZodType` + its 32 methods now extract.
2. ✅ **ENH-008 done** (2026-06-15) — interfaces/enums/types/arrow-consts now
   extracted; verified on zod (Interface/TypeAlias/Variable 0 → 57/241/21).
3. ✅ **Creds-enabled pass done** (2026-06-15) — embed + retrieval + enrich scored
   on live Bedrock. Retrieval is good-not-surgical on this dense target; summaries
   + Factory tags are accurate and precise.
4. Open: retrieval precision on mega-file libraries (chunk lands near, not on) →
   filed **[ENH-009](../enhancements/ENH-009-retrieval-precision-dense-codebases.md)**
   (rerank / symbol-anchoring / summary-augmented embeddings) — not a correctness
   bug. The MCP *agent loop* (W4) still needs `ANTHROPIC_API_KEY`.
