# Bugs

Defects — the system does something **incorrect** (wrong output, broken
feature, degraded data). Distinct from enhancements (works, could be better) and
known-limitations (inherent, not fixable by us).

One file per bug: `BUG-NNN-short-slug.md`. Keep this index current.

## Index

| ID | Title | Severity | Area | Status |
|---|---|---|---|---|
| [BUG-001](BUG-001-src-layout-import-resolution.md) | `src/`-layout breaks in-repo import resolution | High | ingest.resolver | fixed |
| [BUG-002](BUG-002-retrieval-scores-render-zero.md) | Retrieval scores render `0.00` | Medium | retrieve / store.lance | fixed |
| [BUG-003](BUG-003-adr-readme-ingested-as-decision.md) | ADR `README.md` ingested as a Decision | Low | knowledge | fixed |
| [BUG-004](BUG-004-relative-from-import-resolution.md) | Relative `from .module import name` imports under-resolve | High | ingest.resolver | fixed |
| [BUG-005](BUG-005-typescript-abstract-class-not-extracted.md) | TS `abstract class` declarations not extracted | High | ingest.packs.typescript | fixed |
| [BUG-006](BUG-006-commonjs-require-not-resolved.md) | CommonJS `require()` / `module.exports` not captured | High | ingest.packs.javascript | open |

## Template

```markdown
# BUG-NNN: <title>

| Field | Value |
|---|---|
| **ID** | BUG-NNN |
| **Severity** | High / Medium / Low |
| **Status** | open / in-progress / fixed |
| **Found** | YYYY-MM-DD (how) |
| **Area** | package / module |
| **Affects** | feat-NNN |

## Summary
One or two sentences.

## Reproduce
Exact steps / command + minimal input.

## Expected vs actual
- **Expected:** …
- **Actual:** …

## Root cause
The real reason, with `file:line` refs.

## Proposed fix
What to change; alternatives if any.

## Workaround
If one exists today.
```
