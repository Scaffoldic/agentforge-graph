# JavaScript (express + chalk) — validation run

Third W1 run, JavaScript. JS has two module systems, so this run uses **two
repos** to cover both: a CommonJS app (`express`) and an ESM library (`chalk`).

- **repos:** https://github.com/expressjs/express @ `4.19.2` (CommonJS) ·
  https://github.com/chalk/chalk @ `v5.3.0` (ESM)
- **date:** 2026-06-14 (index) · **2026-06-15 (creds-enabled re-run, express `lib/`)**
- **pipeline:** index ✅ · embed ✅ · enrich ✅ (2026-06-15, live Bedrock, express)

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
| **Import resolution** | 0 → **53 in-repo / 386 IMPORTS** after BUG-006 fix (require + module.exports + dir-index) ✅ fixed | 5 in-repo resolved ✅ |
| **Call resolution** | 68 → 71 (most express calls are `app.method()` member calls — unresolved by design, separate limitation) ⚠️ | 12 (cross-file works) ✅ |
| **Impact correctness** | now possible at file/module level (dependency graph exists) ✅ | works ✅ |
| **Retrieval** (creds, 2026-06-15) | **2/4 surgical, 4/4 topically-relevant** (`lib/`, 91 chunks): routing + `res.send` hit exactly; middleware/param questions landed adjacent. Terse, comment-sparse prototype code → low embedding signal (scores 0.36–0.52) | 🟡 fair |
| **Enrichment** (creds, 2026-06-15) | repo + file summaries architecturally accurate (Router/Route/Layer/path-to-regexp); **1 Factory tag** (`createETagGenerator`, 0.75) — precise | ✅ good |
| **MCP agent loop** | needs `ANTHROPIC_API_KEY` (framework Agent is API-key, not Bedrock) | 🟡 pending (W4) |

## Findings

- **[BUG-006](../bugs/BUG-006-commonjs-require-not-resolved.md)** ✅ **fixed this
  run (core)** — CommonJS `require()` (default + named) + `module.exports = name`
  + directory imports are now captured/resolved. express went from **0 → 53
  in-repo imports / 386 IMPORTS edges** — the dependency graph went from empty to
  real. Residual export forms (`module.exports = {…}`/function-expr, `exports.X`)
  tracked in the bug. (ESM JS was already fine — see chalk.)

## Creds-enabled re-run (2026-06-15, live AWS Bedrock, express `lib/`)

Re-indexed express's library tree (`--include 'lib/**' --include 'index.js'`, 12
files) for a clean retrieval target, then embed + enrich on live models. **Cost ≈
$0.02** (embed ~free; tags $0.004; summaries $0.012).

```
indexed 12 files: 49 nodes, 128 edges
  nodes: File=12, Function=37
  edges: CALLS=31, CONTAINS=37, IMPORTS=60
  imports: 12 in-repo + 48 external      ← BUG-006 fix holds on the lib tree
```

(No `Variable` nodes — express's lib has no top-level `const {…}`/`[…]` tables;
its exports are `module.exports = fn` / `exports.X`, which is import/export
modeling, not symbols. Correct.)

**Embeddings** — `ckg embed`: 91 chunks across 9 files, dim 1024. ✅

**Retrieval** — `ckg query`, 4 NL questions:

| Question | Top result | Verdict |
|---|---|---|
| "how is an incoming request routed to a handler" | `router(req,res,next)` (router/index.js) | ✅ exact |
| "how does the response send method work" | `res.send` region (response.js:92-172) | ✅ exact |
| "how is middleware registered and executed" | `lib/express.js` prototype-expose block | 🟡 adjacent |
| "how are route parameters parsed from the url" | `getPathname`/`parseUrl` (router/index.js) | 🟡 adjacent |

Routing and `res.send` land exactly; the middleware/param questions land in the
right file but not on `app.use`/`Layer.match`. express is **terse, comment-sparse,
prototype/factory-style** JS — embeddings have little prose to key on (top scores
only 0.36–0.52), so semantic search is fair rather than sharp. A characteristic of
the codebase, not a tool fault — improvement path filed as
**[ENH-009](../enhancements/ENH-009-retrieval-precision-dense-codebases.md)**
(rerank / symbol-anchoring / summary-augmented embeddings).

**Enrichment — summaries** (12 files + repo): architecturally precise. The repo
summary correctly names the Router/Route/Layer dispatch, path-to-regexp matching,
the Request/Response extensions, and middleware chaining; the router file summary
enumerates the real helpers (`matchLayer`, `mergeParams`, `next`). ✅

**Enrichment — pattern tags**: 3 candidates → **1 tagged**, `createETagGenerator`
as Factory (0.75) — keyed on the `create*` factory verb + options config; 2
candidates rejected. Precise on a framework that is itself factory-shaped. ✅

## What this run validated

- **ESM JavaScript works** — `import … from "./x"` resolves cross-file (chalk),
  via the same `import_statement` mechanism proven on TypeScript. Classes,
  functions, methods extract correctly.
- **CommonJS JavaScript does not** — the single biggest gap found so far for JS.
  The graph is structurally sound (files, functions, intra-file calls) but the
  cross-file dependency graph — the whole point — is empty on `require()` code.

## Next

1. ✅ **BUG-006 fixed** (2026-06-14, core patterns) — express dependency graph
   0→386 IMPORTS. Residual export forms tracked in the bug.
2. ✅ **Creds-enabled pass done** (2026-06-15) — embed + retrieval + enrich scored
   on express `lib/` via live Bedrock. Routing/response retrieval exact; summaries
   + Factory tag accurate. Retrieval is fair (not sharp) on terse prototype JS.
3. W1 now covers all three shipped packs (Python/TS/JS); W3 (the other 7 packs)
   gates the remaining languages. The MCP *agent loop* (W4) still needs
   `ANTHROPIC_API_KEY`.
