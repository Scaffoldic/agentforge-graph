# Design docs

One **design doc per feature**, produced in the *design stage* of the
pipeline (after analysis, before implementation). Naming mirrors the
feature number:

```
design-NNN-slug.md   ↔   docs/features/feat-NNN-slug.md
```

## Why a separate doc (vs designing inline)

The feature spec answers *what & why* and is the contract. The design
doc answers *how* — concrete file layout, exact types/signatures,
resolved open questions, the test plan, and the **chunk plan** (the
commits that will make up the single feature PR). It is the artifact
the user reviews and approves before any code is written, and it stays
as the record of *why the implementation looks the way it does*.

Cross-cutting designs that span multiple features use a topical slug
instead (`design-<topic>.md`), per the workspace template.

## Lifecycle

`draft` → (user approves) → `accepted` → (feature ships) stays as
history. Supersede with a new doc; never delete.

## Index

| Design | Feature | Status |
|---|---|---|
| [design-001-core-contracts-module](design-001-core-contracts-module.md) | feat-001 | accepted |
| [design-009-temporal-evolution-layer](design-009-temporal-evolution-layer.md) | feat-009 | accepted |
| [design-015-read-only-graph-query](design-015-read-only-graph-query.md) | feat-015 | accepted |

_(Add a row per feature as its design is written.)_
