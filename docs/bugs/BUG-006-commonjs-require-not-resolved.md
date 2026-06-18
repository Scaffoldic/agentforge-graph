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

**Residual — `module.exports = function name(){}` ✅ closed (2026-06-15,
`bug/006-residual-fn-export`):** the named function-expression default export (the
express-style router factory, incl. chained `var p = module.exports = function
name(){}`) is now extracted as a `Function` symbol AND marked the module default
export, so `const r = require("./m"); r()` resolves to it. Verified on express
`lib/`: `router/index.js`'s `module.exports = function router(){}` now appears as
a Function (Function 37→38, its default-require CALL now resolves). Anonymous
`module.exports = function(){}` / `= () => {}` have no name → no symbol (the
IMPORTS edge still exists). Note: `module.exports = { a, b }` needs **no** special
handling — named destructure (`const { a } = require("./m")`) already binds via
the resolver's by-name top-level export map.

**Residual — intra-class member calls ✅ closed (2026-06-17,
`bug/006-self-this-member-calls`):** the reference queries now capture the call
*receiver* (`@call.recv`) for Python / TypeScript / JavaScript, so the resolver
binds `self.f()` / `this.f()` to a method **of the enclosing class** — a unique,
safe match that recovers the intra-class call graph (previously these were
unresolved, or — worse — silently mis-bound to a same-named module-level def).
A member call on *any other* receiver (`obj.f()`, `a.b.f()`) is now explicitly
left unresolved rather than guessed (ADR-0004). Verified on Python/TS/JS:
`self.handle()`/`this.handle()` resolves to `Service#handle`, never the
module-level `handle` decoy; `s.handle()` on a parameter stays unresolved.

**Residual — receiver capture for the rest of the packs ✅ mostly closed
(2026-06-17, `bug/006-member-calls-all-packs`):** Java / C# / Rust / Ruby / PHP
now capture `@call.recv`, so `this.f()` / `self.f()` / `$this->f()` /
`self::f()` resolve to the enclosing class's method (same resolver path; the
self-receiver set is `{self, this, $this}`). The extractor dedupes by call node
so the Java/Ruby grammars — one node type for `f()` and `recv.f()` — don't
double-record. Verified per language. **Two packs deferred:** **Go** (the
receiver is a *named* variable, e.g. `func (s *Server)`, not a keyword — needs
the resolver to learn the method's receiver var) and **C++** (the pack doesn't
yet model inline struct/class methods as symbols, so there's no method node to
bind to).

**Residual — Go receiver-variable calls ✅ closed (2026-06-17,
`feat/go-receiver-calls`):** Go's receiver is a named variable (`func (s *T)`),
not a keyword, so the extractor now records each method's receiver var + type,
and the resolver indexes methods by (package, type). A call on the method's own
receiver (`s.f()`) binds to a method of that type — more precise than the prior
bare-name match (which could hit another type's same-named method). Verified two
types with a same-named method don't cross-bind.

**Residual (still open — file as ENH when prioritised):**
- **C++ method modeling** — the cpp pack doesn't extract inline struct/class
  methods as symbols, so `this->f()` has nothing to bind to.
- **Inherited-method `self.f()`** ✅ closed for Python (#66) and extended to
  **TS / JS / Java / C# / Ruby / PHP** (2026-06-17, `feat/inherits-other-packs`):
  each pack now captures its `extends`/`<`/`:` superclass, so `INHERITS` edges +
  inherited-method calls work across all eight OO packs. A `self.f()` not on the
  enclosing class binds to the base method when exactly one base defines it (own
  override wins; multi-definer ambiguous → unresolved, no MRO guessing). Rust
  (trait impls), Go (embedding) and C++ (method modeling) use different models —
  follow-ups; implemented interfaces (`implements`) are a separate (IMPLEMENTS)
  relation, not captured.
- **Module-member access** `m.f()` ✅ partially closed (2026-06-17,
  `bug/006-module-member-access`): the resolver now tracks receiver→module
  aliases for whole-module imports (`import m`) and default requires (`const m =
  require("./m")`), so `m.f()` binds to module `m`'s top-level export `f`.
- **Export-member modeling (JS)** ✅ closed (2026-06-18,
  `bug/006-export-member-modeling`): assigned-property exports whose value is an
  *anonymous* function — `exports.foo = function(){}` / `= () => {}`,
  `module.exports.foo = …`, and inline-function values in `module.exports = {
  foo: () => {} }` — are now extracted as `Function` symbols named for the
  property (the export name). Previously these had no symbol to bind to, so
  `m.foo()`, `const { foo } = require(...)`, and direct calls were unresolved;
  they now resolve through the existing export map. Non-function assignments
  (`exports.x = someVar`, re-export of an existing binding) mint no symbol
  (ADR-0004); shorthand `{ a, b }` object exports naming top-level defs already
  resolved. JS-only — TS/Python use `import`/`export`.
- **Qualified bases** `class B extends mod.Base` / `class B(mod.Base)` ✅ closed
  (2026-06-18, `bug/006-qualified-bases`): the structure packs (Python, JS, TS)
  now capture a qualified/member base expression, and the resolver splits the
  receiver and binds it via the importing **module alias** (`import mod` /
  `const mod = require(...)` / `import * as mod from …`), reusing the same alias
  map as module-member calls. This emits the `INHERITS` edge *and* lets inherited
  `self.f()`/`this.f()` calls resolve through it. To make the TS namespace case
  work, ESM namespace imports (`import * as ns from "./m"`) are now captured too
  (previously they produced no IMPORTS edge or alias at all). A qualified base
  whose receiver is not an imported module stays unresolved (ADR-0004).
- **Still open:** aliased imports (`import os.path as osp` / `from pkg import mod`
  as a submodule alias) don't capture the alias yet; `import x = require(...)`
  CommonJS-in-TS, and ESM `export { x }` / re-export chains (explicit export
  modeling would unify these).

## Notes

ESM JS is unaffected (validated on chalk). The residuals are about *which* export
forms bind; the dependency (`IMPORTS`) graph is now produced for CommonJS either
way, which is the primary value for impact analysis.
