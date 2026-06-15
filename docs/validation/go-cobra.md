# spf13/cobra (Go) — validation run

First Go run (W3, first non-{Py,TS,JS} pack): a real, idiomatic, widely-used Go
library (the de-facto CLI framework). Exercises the **directory-package** import
model — a large single `cobra` package spread over many files, plus a `doc`
sub-package that imports the root package.

- **repo:** https://github.com/spf13/cobra @ `v1.8.0`
- **date:** 2026-06-15
- **pipeline:** index ✅ · embed ⬜ · enrich ⬜ (structural validation; creds pass later)
- **command:** `ckg index /tmp/cobra --exclude '**/*_test.go'` (default config)

## Counts

```
indexed 19 files: 340 nodes, 972 edges
  nodes: Class=8, File=19, Function=100, Method=158, TypeAlias=5, Variable=50
  edges: CALLS=511, CONTAINS=321, IMPORTS=140
  imports: 12 in-repo + 128 external
  calls:   511 resolved / 962 unresolved
```

## Scores

| Dimension | Result | Verdict |
|---|---|---|
| **Parse coverage** | 19/19 non-test files parsed, 0 skipped | ✅ excellent |
| **Symbol extraction** | 8 structs (`Command`→Class), 100 funcs, 158 methods (`Execute`/`AddCommand`/`Flags`→Method), 5 defined types (→TypeAlias), 50 package const/var (→Variable) — the full Go surface | ✅ strong |
| **Same-package cross-file calls** | **511 CALLS resolved** — cobra is one big package over ~15 files; sibling calls (no import in Go) resolve via the dir-level export merge. This is the hard part of Go, and it works at scale | ✅ strong |
| **Import resolution — sub & root** | 12 in-repo: `doc` → root `cobra` package resolves via the **go.mod module prefix** (`github.com/spf13/cobra` stripped → root dir key `""`). Sub-package imports resolve by suffix-match. `fmt`/`os`/third-party stay external (128) | ✅ good |
| **Call resolution rate** | 511/1473 ≈ 35% — unresolved dominated by **method/selector calls** (`cmd.Flags()`, `pkg.Func()`) and external stdlib, which Go expresses as member access (ADR-0004 leaves these unresolved, never guessed) | ⚠️ expected |
| **Routes / decisions** | none (a CLI library) — correctly empty | ✅ n/a |
| **Retrieval / enrichment / MCP** | not run this pass (structural validation first) | ⬜ pending |

## What this run validated

- **The harness generalizes to a directory-level language.** Go is the first pack
  where a *package is a directory*, not a file. Two small, pack-agnostic resolver
  changes carried it: (1) merge every file's top-level defs into the package's
  export map → **same-package cross-file calls resolve** (Go needs no import
  within a package); (2) strip the **go.mod module prefix** (with a leading-segment
  suffix-match fallback) → import paths map to in-repo package dirs, including the
  *root* package whose dir key is `""`.
- **Symbol extraction is comprehensive** on real Go: structs, interfaces, defined
  types/aliases, funcs, receiver methods, package const/var.
- **The honest gaps are by-design**: struct **fields** aren't symbols (e.g.
  `Command.Args`/`ValidArgs` — consistent with not extracting class attributes in
  other packs), and **selector calls** (`x.Method()` / `pkg.Func()`) stay
  unresolved (the member-access limitation, ADR-0004 — shared with all packs).

## Findings

- No correctness bug. The Go pack ships with: func/method/struct/interface/
  defined-type/const/var extraction, same-package cross-file call resolution, and
  go.mod-aware + suffix-match import resolution.
- **Follow-ups (not blockers):**
  - **Receiver→method `CONTAINS` linkage** — Go methods are package-scoped
    (`func (c Circle) Area()`), so they're currently file-owned, not linked to
    their receiver type (which may live in another file). Linking them would make
    `Command`'s methods navigable from the `Command` node.
  - **Struct-field extraction** — fields like `Command.Args` aren't captured
    (matches other packs; revisit if field-level retrieval proves valuable).
  - Selector/member call resolution is the shared ADR-0004 boundary.

## Next

1. ✅ **Go pack shipped + validated on cobra** (this run).
2. A creds-enabled pass (embed + retrieval + enrich) on a Go repo, alongside the
   other packs.
3. Continue W3: the next Tier-A pack (Java/C#/Rust/Ruby/PHP) over the same harness.
