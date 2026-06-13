# BUG-003: ADR `README.md` / index files ingested as a Decision

| Field | Value |
|---|---|
| **ID** | BUG-003 |
| **Severity** | Low |
| **Status** | fixed |
| **Found** | 2026-06-13 (end-to-end dogfood) |
| **Fixed** | 2026-06-13 (`bug/e2e-eval-fixes`) — `KnowledgeIngestor._discover` skips stems `readme`/`index`/`template`/`_template`/`0000-template`. Verified: this repo's Decision count dropped 10 → 9 (README excluded). |
| **Area** | `knowledge.ingest` / `knowledge.adr` |
| **Affects** | feat-010 (`ckg decisions`, `ckg_decisions`) |

## Summary

`docs/adr/README.md` (an index/landing page, not an ADR) is ingested as a
`Decision` node — and mis-statused as `superseded` because that word appears in
the page listing other ADRs.

## Reproduce

```
ckg index .            # repo with docs/adr/README.md
ckg decisions
# → "superseded  —  docs/adr/README.md  Architecture Decision Records"
```

## Expected vs actual

- **Expected:** `README.md` / `index.md` / `template.md` under the ADR globs are
  **not** treated as decisions.
- **Actual:** the README becomes a `Decision` (no `adr_id`, status guessed
  `superseded` from incidental text), polluting `ckg decisions` and the
  Decision node count.

## Root cause

`KnowledgeIngestor._discover` (`knowledge/ingest.py`) globs `adr_globs`
(`docs/adr/**/*.md`), which matches `README.md`. `ADRParser.parse`
(`knowledge/adr.py`) then produces a `Decision` from any markdown — its
filename-title fallback and `_status_from` (which scans the body for a status
word) fire on the README's prose. There is no filter for non-ADR files.

## Proposed fix

Filter obvious non-ADR files in `_discover`:

- Skip stems matching `readme` / `index` / `template` (case-insensitive).
- Optionally require an ADR shape: a numbered filename (`NNNN-…`) **or** a
  frontmatter/`Status` section, controllable via config
  (`knowledge.require_adr_number: bool`). Default to skipping README/index/
  template, which covers the common case without excluding number-less ADRs.

Add a fixture with a `README.md` alongside real ADRs and assert it is excluded.

## Workaround

Set `knowledge.adr_globs` to a stricter pattern (e.g.
`docs/adr/[0-9]*.md`) in `ckg.yaml`.
