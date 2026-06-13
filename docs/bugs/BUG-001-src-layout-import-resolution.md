# BUG-001: `src/`-layout breaks in-repo import resolution

| Field | Value |
|---|---|
| **ID** | BUG-001 |
| **Severity** | High |
| **Status** | fixed |
| **Found** | 2026-06-13 (end-to-end dogfood on this repo) |
| **Fixed** | 2026-06-13 (`bug/e2e-eval-fixes`) — `ImportResolver` auto-detects source roots (parent of a top-level `__init__.py` package, e.g. `src/`) and strips them when computing module keys for dotted-namespace packs. Verified: this repo now resolves 94 in-repo imports (was 0). Explicit `ingest.source_roots` config override deferred (ENH). |
| **Area** | `ingest.resolver` / `ingest.pack` |
| **Affects** | feat-002 (resolution), and everything downstream (impact/context retrieval, repo-map ranking, pattern Repository/Service signals that lean on edges) |

## Summary

On a `src/`-layout repository (package under `src/`, the dominant Python
layout), **zero in-repo imports resolve** — every `import` is classified
external. Cross-file `IMPORTS`/`CALLS` edges between the project's own modules
are therefore missing.

## Reproduce

```
ckg index . --include "src/**/*.py"   # on this repo
# → "resolve: imports 0 in-repo + 226 external, calls 127 resolved / 1818 unresolved"
```

## Expected vs actual

- **Expected:** `from agentforge_graph.core import X` in
  `src/agentforge_graph/ingest/resolver.py` resolves to the in-repo file
  `src/agentforge_graph/core/__init__.py`, producing an `IMPORTS` edge and
  enabling `CALLS` resolution to that module's symbols.
- **Actual:** 0 in-repo imports; all 226 imports counted external; the import
  graph between own modules is empty.

## Root cause

`LanguagePack.module_path()` (`ingest/pack.py`) derives a module key from the
**full repo-relative path**: `src/agentforge_graph/core/models.py` →
`src.agentforge_graph.core.models`. The resolver indexes files under that key
(`ImportResolver.resolve`, `resolver.py:54` builds `module_to_file` via
`pack.module_path(ps.path)`). But the *import as written* is
`agentforge_graph.core` (dotted, `resolve_import` is identity for Python). So the
lookup key `agentforge_graph.core` never matches the indexed key
`src.agentforge_graph.core` → falls through to the external branch
(`resolver.py:116`). The resolver has no concept of a **source root** (`src/`)
that is a prefix of file paths but not part of the import namespace.

## Proposed fix

Give the pipeline a notion of source roots and strip them before computing
module keys:

1. **Config:** `ingest.source_roots: list[str] = []` (e.g. `["src"]`).
   `module_path` (or the resolver, before indexing) strips a leading
   source-root segment from the path.
2. **Auto-detect (preferred default):** a directory is a source root if it
   contains a package but is **not itself a package** — i.e. it has no
   `__init__.py` yet contains a child dir that does (classic `src/` layout). Also
   honour `pyproject.toml` `[tool.hatch.build…].packages` / `[tool.setuptools]`
   `package-dir` when present. Strip the detected root(s) from module keys.
3. Apply symmetrically to `module_path` (the file's key) and `resolve_import`
   (the importer's key) so both sides agree.

Add a `src/`-layout fixture to the resolver tests (a package under `src/` whose
modules import each other by their installed name).

## Workaround

Index from inside the package root so paths don't carry the `src/` prefix —
e.g. `cd src && ckg index .` — at the cost of losing repo-root files (docs/ADRs)
from that run. Not viable when you also want decisions/docs ingested.
