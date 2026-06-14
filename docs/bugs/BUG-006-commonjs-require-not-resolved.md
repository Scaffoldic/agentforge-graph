# BUG-006: CommonJS `require()` / `module.exports` are not captured

| Field | Value |
|---|---|
| **ID** | BUG-006 |
| **Severity** | High |
| **Status** | fixed (core patterns; residuals tracked below) |
| **Found** | 2026-06-14 (W1 validation on `expressjs/express` 4.19.2) |
| **Fixed** | 2026-06-14 (`bug/006-commonjs-require`) — JS `structure.scm` now captures `const x = require("./m")` (default), `const {a,b} = require("./m")` (named), and `module.exports = <name>` (default export); the resolver binds default requires to the target module's default export and resolves directory imports (`./router` → `./router/index`). Re-run on express: in-repo imports **0→53**, IMPORTS edges **0→386** (the dependency graph went from empty to real). ESM unaffected. |
| **Area** | `ingest.packs.javascript` (`structure.scm`) / `ingest.extractor` / `ingest.resolver` |
| **Affects** | feat-002 (JS import resolution) and everything downstream — on CommonJS repos there are **no cross-file edges**, so impact/neighbors/retrieval are empty |

## Summary

The JavaScript pack captures only ESM `import … from "…"`. CommonJS — `const x =
require("./y")`, `const { a } = require("./y")`, `module.exports = …`,
`exports.foo = …` — is **not captured at all**. On a CommonJS repository the
import graph is empty: zero imports resolve, so no cross-file `IMPORTS`/`CALLS`
edges exist. CommonJS is still the dominant module system across Node/npm, so this
is a major hole in JS support, not an edge case.

## Reproduce

```bash
git clone --depth 1 --branch 4.19.2 https://github.com/expressjs/express /tmp/express
ckg index /tmp/express
# resolve: imports 0 in-repo + 0 external, calls 68 resolved / 11635 unresolved
#          IMPORTS=0
```

Contrast — ESM JS resolves fine (`chalk` v5):
```
ckg index /tmp/chalk   # imports 5 in-repo + 7 external, IMPORTS=12
```

## Root cause

`require` is a **call expression**, not an `import_statement`, so the JS
`structure.scm` (which matches only `import_statement … source: (string …)`)
never sees it. The export side (`module.exports` / `exports.x`) is likewise not
modeled.

## Fix sketch (feature-sized — design as its own unit)

This is bigger than a one-line query add; do it deliberately:

1. **Capture require imports** in the JS `structure.scm`: a `lexical_declaration`
   whose initializer is `require("<path>")`, covering both
   `const NAME = require("./m")` (default binding) and
   `const { a, b } = require("./m")` (named bindings). Emit an import record
   `{module: "./m", names: [...]}` — the relative-path `resolve_import` already
   handles `./m`.
2. **Model `module.exports` / `exports.x`** so imported names bind on the export
   side. The resolver currently binds an imported name to any top-level def of the
   target module *by name*; that covers `const { Router } = require("./router")`
   when `router.js` has a top-level `Router`, but **not** `module.exports = fn`
   (default export rebound under a new name, as express does). Handling the
   default/`module.exports` case needs an explicit export mapping.
3. Add CommonJS fixtures to the JS pack conformance (default + named require,
   `module.exports` + `exports.x`); assert cross-file IMPORTS + CALLS resolve.

A scoped first pass (named-destructure require → existing by-name binding) would
recover part of the graph; full parity needs the `module.exports` mapping.

## Shipped vs residual

**Shipped (this fix):**
- `const x = require("./m")` (default) + `const { a, b } = require("./m")` (named).
- `module.exports = <identifier>` (incl. chained `exports = module.exports = name`)
  → module default export, so a default require binds to that symbol.
- Directory imports: `require("./router")` → `./router/index` (also helps ESM/TS).

**Residual (follow-ups — file as ENH when prioritised):**
- `module.exports = { … }` / `module.exports = function () {}` (object/function-
  expression default exports — e.g. express's `application.js` prototype object).
- `exports.Name = …` named exports (these feed *member* access `pkg.Name()`,
  which the resolver doesn't resolve regardless — a separate limitation).
- `import x = require(...)` CommonJS-in-TS, and ESM `export { x }` / re-export
  chains (explicit export modeling would unify these).

## Notes

ESM JS is unaffected (validated on chalk). The residuals are about *which* export
forms bind; the dependency (`IMPORTS`) graph is now produced for CommonJS either
way, which is the primary value for impact analysis.
