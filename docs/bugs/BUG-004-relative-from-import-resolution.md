# BUG-004: relative `from .module import name` imports under-resolve

| Field | Value |
|---|---|
| **ID** | BUG-004 |
| **Severity** | High |
| **Status** | fixed |
| **Found** | 2026-06-14 (W1 validation on `pallets/click` 8.1.7) |
| **Fixed** | 2026-06-14 (`bug/004-relative-import-resolution`) — two parts: (1) the Python `structure.scm` now captures `module_name: (relative_import)` (relative imports were never matched, so dropped entirely); (2) `LanguagePack.resolve_import` resolves leading-dot module keys against the importer's package. Re-run on click: in-repo imports **56→109**, resolved CALLS **292→404**, `echo` callers **0→18**, `impact(echo)` **1→19**. |
| **Area** | `ingest.resolver` / `ingest.pack` |
| **Affects** | feat-002 (resolution) and everything downstream — impact analysis, context retrieval, repo-map ranking, pattern signals that lean on `CALLS`/`IMPORTS` edges |
| **Relates to** | [BUG-001](BUG-001-src-layout-import-resolution.md) (fixed *absolute* src-layout imports; this is the *relative* path) |

## Summary

On an idiomatic intra-package layout that uses **relative imports**
(`from .utils import echo`), calls to the imported symbol are **not** resolved to
its definition — even though the symbol has a single, unambiguous definition and
is called directly by name. This silently drops a large share of the most
valuable edges (cross-module CALLS within a package), so impact analysis
undercounts.

## Reproduce

```bash
git clone --depth 1 --branch 8.1.7 https://github.com/pallets/click /tmp/click
ckg index /tmp/click
# resolve: imports 56 in-repo + 190 external, calls 292 resolved / 3894 unresolved
```

Then inspect `echo` (defined once in `src/click/utils.py`, imported via
`from .utils import echo` in `core.py`, `termui.py`, `decorators.py`,
`shell_completion.py`, `exceptions.py`, `_termui_impl.py`, and called bare 29×
in `src/`):

- **incoming `CALLS` to `echo`: 0** (expected: dozens)
- **`impact(echo)` returns only `echo` itself** — 0 callers
- supporting: only **1** resolved `IMPORTS` edge lands on `src/click/utils.py`
  despite 6+ `from .utils import …` sites

## Expected vs actual

- **Expected:** `from .utils import echo` in `core.py` binds the name `echo` to
  `src/click/utils.py :: echo`; a subsequent bare `echo(...)` resolves to that
  definition (an `IMPORTS` edge + `CALLS` edges).
- **Actual:** the binding isn't established for relative (`from .x import y`)
  imports, so the bare calls fall through to "unresolved" and `echo` shows no
  callers.

Note this is **not** ADR-0004 conservatism: `echo` has exactly one definition
node (no ambiguity to refuse). General cross-file resolution *does* work — 109 of
292 resolved CALLS are cross-file — so the gap is specific to the relative-import
name binding, not cross-file resolution as a whole.

## Root cause (confirmed)

Two compounding defects — the first was bigger than the initial hypothesis:

1. **The query never captured relative imports.** Python's `structure.scm`
   matched only `module_name: (dotted_name)`. The grammar parses
   `from .utils import echo` with a **`relative_import`** node (leading-dot
   `import_prefix` + optional `dotted_name`), so the pattern didn't match and the
   import — and its bound names — were **dropped entirely** at extraction. No
   `IMPORTS` record ever reached the resolver.
2. **`resolve_import` couldn't resolve the dots.** Even once captured, the dotted
   pack returned the raw module key as identity, so `.utils` never matched the
   absolute key `click.utils` in the module index.

## Fix

- `structure.scm`: add `(import_from_statement module_name: (relative_import)
  @import.module …)` so relative imports are captured (the node text — `.utils`,
  `..pkg.mod`, `.` — becomes the raw module).
- `LanguagePack.resolve_import(importer_path, raw_module, importer_module)`:
  count leading dots and resolve against the importer's (source-root-stripped)
  module key — one dot = the importer's package, each extra dot ascends a level.
- `resolver.py` passes the importer's `file_module` key through.
- Tests: `resolve_import` dot cases (`test_pack.py`) + an end-to-end
  relative-import regression (`test_src_layout.py`).

## Impact on the 0.1 bar

Relative intra-package imports are the dominant style inside real Python
packages. Until this resolves, impact/neighbors/retrieval systematically
under-report intra-package usage — exactly the queries the CKG exists to answer.
This is a W1 blocker, not a nice-to-have.

## Fix sketch

- Detect leading-dot imports; resolve the level (`.` = current package, `..` =
  parent) against the importing file's package, then the remainder, to the
  in-repo module key already used for absolute imports.
- Add a relative-import fixture to the resolver conformance suite (Python pack),
  and a regression assertion on the click run (echo gains callers).
