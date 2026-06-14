# JavaScript (express + chalk) — validation run

Third W1 run, JavaScript. JS has two module systems, so this run uses **two
repos** to cover both: a CommonJS app (`express`) and an ESM library (`chalk`).

- **repos:** https://github.com/expressjs/express @ `4.19.2` (CommonJS) ·
  https://github.com/chalk/chalk @ `v5.3.0` (ESM)
- **date:** 2026-06-14
- **pipeline:** index ✅ · embed/enrich ⬜ (no live model creds)

## Counts

```
express (CommonJS):
  152 files: 296 nodes, 212 edges
  nodes: File=152, Function=144      (no classes — express is prototype/factory style)
  edges: CALLS=68, CONTAINS=144, IMPORTS=0
  imports: 0 in-repo + 0 external    ← CommonJS require() not captured at all

chalk (ESM):
  19 files: 41 nodes, 46 edges
  nodes: File=19, Class=1, Function=20, Method=1
  edges: CALLS=12, CONTAINS=22, IMPORTS=12
  imports: 5 in-repo + 7 external    ← ESM imports resolve
```

## Scores

| Dimension | express (CommonJS) | chalk (ESM) |
|---|---|---|
| **Parse coverage** | 152/152 ✅ | 19/19 ✅ |
| **Symbol extraction** | functions extracted ✅ (no classes — correct for express) | class + functions + method ✅ |
| **Import resolution** | **0** — `require()` / `module.exports` not captured ❌ **BUG-006** | 5 in-repo resolved ✅ |
| **Call resolution** | 68 (intra-file only — no import graph to cross) ⚠️ | 12 (cross-file works) ✅ |
| **Impact correctness** | impossible — no cross-file edges on CommonJS ❌ (BUG-006) | works ✅ |
| **Retrieval / enrichment / MCP** | not run — no creds | not run — no creds |

## Findings

- **[BUG-006](../bugs/BUG-006-commonjs-require-not-resolved.md)** — CommonJS
  `const x = require("./y")` / `module.exports` are not captured, so a CommonJS
  repo resolves **0 imports** and has no cross-file graph (no impact analysis).
  CommonJS is still the dominant module system across the Node ecosystem, so this
  is a major gap in JS support — **High**. (ESM JS is unaffected — see chalk.)

## What this run validated

- **ESM JavaScript works** — `import … from "./x"` resolves cross-file (chalk),
  via the same `import_statement` mechanism proven on TypeScript. Classes,
  functions, methods extract correctly.
- **CommonJS JavaScript does not** — the single biggest gap found so far for JS.
  The graph is structurally sound (files, functions, intra-file calls) but the
  cross-file dependency graph — the whole point — is empty on `require()` code.

## Next

1. **BUG-006** is feature-sized (capture `require()` imports *and* `module.exports`
   for the binding side) — design it as its own unit, not a one-line query add.
2. A creds-enabled pass for retrieval/enrichment/MCP (W2/W4).
3. W1 now covers all three shipped packs (Python/TS/JS); W3 (the other 7 packs)
   gates the remaining languages.
