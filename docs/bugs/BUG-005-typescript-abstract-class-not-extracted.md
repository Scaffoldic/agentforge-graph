# BUG-005: TypeScript/JavaScript `abstract class` declarations are not extracted

| Field | Value |
|---|---|
| **ID** | BUG-005 |
| **Severity** | High |
| **Status** | open |
| **Found** | 2026-06-14 (W1 validation on `colinhacks/zod` v3.23.8) |
| **Area** | `ingest.packs.typescript` / `ingest.packs.javascript` (`structure.scm`) |
| **Affects** | feat-002 (extraction) and everything downstream — abstract base classes, their methods, `extends`/impact edges, repo-map centrality |

## Summary

`abstract class Foo {}` is **not extracted** — no Class node, and its methods and
inheritance edges go with it. In TypeScript an abstract class parses as an
`abstract_class_declaration` node, distinct from `class_declaration`, and the TS
`structure.scm` matches only the latter. Abstract classes are a common (often the
most central) base type, so the omission is high-impact.

## Reproduce

```bash
git clone --depth 1 --branch v3.23.8 https://github.com/colinhacks/zod /tmp/zod
ckg index /tmp/zod
```

- `ZodType` — the abstract base class every `Zod*` schema `extends` — is **absent**
  from the graph, while concrete `ZodString`/`ZodObject`/… are present.
- Confirmed against the grammar: `export abstract class ZodType<…> {}` →
  `abstract_class_declaration` (the `class_declaration` query never matches it).

## Expected vs actual

- **Expected:** `abstract class ZodType {}` produces a `Class` node (like any
  class), owns its methods via `CONTAINS`, and is the target of `extends ZodType`.
- **Actual:** no node; `ZodType`'s methods are orphaned/dropped; `extends ZodType`
  cannot resolve; impact/centrality for the library's root type is empty.

## Root cause

`src/agentforge_graph/ingest/packs/typescript/structure.scm` (and the JS pack,
which reuses the same shape) captures:

```
(class_declaration name: (type_identifier) @name) @def.class
```

TypeScript's grammar emits a separate `abstract_class_declaration` node for
`abstract class …`; it isn't matched, so the definition is skipped at extraction.

## Fix sketch

- Add an `(abstract_class_declaration name: (type_identifier) @name) @def.class`
  pattern to the TS `structure.scm` (maps to the same `Class` kind). Verify the
  JS pack (JS has no `abstract`, so likely TS-only) and the shared extractor still
  promote nested methods to `METHOD`.
- Add a fixture with an abstract class + a concrete subclass to the TS pack
  conformance; assert the abstract class node, its methods, and the `extends`
  relationship resolve. Re-run zod and confirm `ZodType` appears with methods.

## Notes

Distinct from ENH-008 (broader TS symbol vocabulary: interfaces, enums, type
aliases, arrow-`const` functions). An abstract class *is* a class — this is a
missed case of an already-supported kind, hence a bug, not a scope expansion.
