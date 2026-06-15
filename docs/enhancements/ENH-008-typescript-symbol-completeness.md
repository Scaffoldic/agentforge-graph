# ENH-008: broaden TypeScript/JavaScript symbol extraction

| Field | Value |
|---|---|
| **ID** | ENH-008 |
| **Value/Impact** | Medium–High (large share of real TS surface is non-class/function) |
| **Effort** | M |
| **Status** | **done** (2026-06-15) |
| **Area** | `ingest.packs.typescript` / `ingest.packs.javascript` |
| **Relates to** | feat-002 (extraction); follows W1 validation on zod |

## Motivation

The TS/JS packs currently extract **classes, functions, and methods** only. Real
TypeScript exposes much of its surface through constructs the packs ignore:

- **`interface`** declarations (the dominant way TS describes shapes/contracts).
- **`enum`** and `const`-object enums (e.g. zod's `ZodIssueCode`,
  `ZodFirstPartyTypeKind`).
- **`type` aliases** (e.g. `ZodParsedType`).
- **arrow / `const`-assigned functions** (`export const f = (…) => …`) — pervasive
  in modern TS/JS; today they produce no Function node.

On the zod validation run, `ZodIssueCode`, `ZodFirstPartyTypeKind`, and
`ZodParsedType` were all absent — a meaningful chunk of the public API is invisible
to search, repo-map, and retrieval.

## Current behavior

`structure.scm` (TS/JS) captures `class_declaration`, `function_declaration`, and
class-body methods (`property_identifier`). Interfaces, enums, type aliases, and
variable-bound arrow/function expressions are not captured.

## Proposed change

Extend the TS/JS `structure.scm` (and the shared kind mapping) to capture:

1. `interface_declaration` → a node kind (reuse `Class`, or introduce an
   `Interface` kind — decide during design; `Class` keeps the schema small).
2. `enum_declaration` → `Class`/`Enum`.
3. `type_alias_declaration` → a lightweight `Type` node (or skip if low value).
4. `lexical_declaration` with an `arrow_function`/`function` initializer →
   `Function` (named from the binding identifier).

Each addition needs a conformance fixture and a decision on the node kind (avoid
kind sprawl — prefer mapping onto existing kinds unless an edge type needs the
distinction). Sequence after BUG-005 (abstract classes), which is a strict bug.

## Acceptance criteria

- On zod, `ZodIssueCode` / `ZodFirstPartyTypeKind` / `ZodParsedType` and exported
  arrow-`const` helpers appear in the graph and are searchable.
- New kinds (if any) are reflected in the schema, conformance suite, and the MCP
  tool outputs without breaking the locked v1 tool schemas.
- No regression to class/function/method extraction.

## Resolution (2026-06-15)

Extended `structure.scm` for both packs + the kind maps. New TS captures:
`interface_declaration` → **Interface**, `enum_declaration` (incl. `const enum`)
→ **Class** (no dedicated Enum kind — a named nominal type), `type_alias_declaration`
→ **TypeAlias**. New TS+JS captures: arrow/function-bound consts (`const f = (…) =>
…` / `= function(){}`) → **Function** (named from the binding, at any depth), and
**top-level** `const` object/array tables → **Variable**.

Two scoping decisions kept sprawl down: (1) Variable capture is **program/export
top-level only**, so locals inside function bodies don't inflate the graph; (2)
call-result consts are **deliberately not** captured as Variables — `const x =
require(...)` is an import binding (BUG-006) and capturing it would shadow the
cross-file CALL resolution. Call-bound public constants (zod's `ZodIssueCode =
arrayToEnum([...])`) stay findable via their companion `type X = …` alias. All
new kinds were already in the locked v1 vocabulary (ADR-0005), so no schema
change. Conformance fixtures added to both pack tests. 400 passed, 97%.

## Notes

Pairs with BUG-005. Keep an eye on node-kind sprawl — the value is making the
symbols *findable*; a new `EdgeKind`/`NodeKind` is only worth it when a query
needs to distinguish (e.g. `IMPLEMENTS` an interface).
