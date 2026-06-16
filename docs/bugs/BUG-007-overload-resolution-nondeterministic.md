# BUG-007: same-named (overloaded) symbol resolution is store-order dependent

| Field | Value |
|---|---|
| **ID** | BUG-007 |
| **Severity** | Medium |
| **Status** | fixed (`bug/007-overload-resolution-determinism`) |
| **Found** | 2026-06-16 (pre-0.1 validation item 2 — incremental == full on real churn, `pallets/click`) |
| **Fixed** | 2026-06-16 — sort CONTAINS members by node id before building the export name→id map in `ingest/resolver.py`, so the last-write-wins selection among same-named callables is deterministic. |
| **Area** | `ingest.resolver` (`ImportResolver.resolve` — per-module export map) |
| **Affects** | feat-004 (incremental == full re-index contract) — CALLS edge targets only; node/edge *sets* were already correct |

## Summary

When a file declares **several same-named top-level callables** — e.g. Python
`@typing.overload` stubs plus the implementation (`convert_type`, `command`,
`get_current_context`, `edit`, `_get_argv_encoding` in click) — a call to that
name resolved to a *different* (but equally valid) overload instance depending on
whether the graph was built **incrementally** or via a **full** re-index. The two
graphs were structurally identical except for these CALLS edge endpoints, which
violates the feat-004 contract that an incremental `refresh` produces the same
graph as a full re-index (modulo provenance timestamps).

## Reproduce

Index a repo with overloaded functions at an old commit, incrementally re-index
to a newer commit, and full-index the newer commit separately; the graphs differ
only on CALLS edges into overloaded symbols:

```bash
git clone https://github.com/pallets/click /tmp/a && cp -R /tmp/a /tmp/b
git -C /tmp/a checkout 82f377c && ckg index /tmp/a --lang py        # initial
git -C /tmp/a checkout 1ca1cea && ckg index /tmp/a --lang py        # incremental
git -C /tmp/b checkout 1ca1cea && ckg index /tmp/b --lang py --full # full baseline
# graph diff (normalizing the repo-dir token in node ids): 12 CALLS edges differ,
# each caller -> same callee *name* but a different overload disambiguator, e.g.
#   prompt() -> convert_type(+3)   (incremental)
#   prompt() -> convert_type(+1)   (full)
```

Node sets, edge counts, and every non-CALLS edge matched exactly; only the
overload *choice* diverged.

## Root cause

In `ImportResolver.resolve`, the per-module export map is built last-write-wins:

```python
members = await store.neighbors(f.id, [EdgeKind.CONTAINS], depth=1)
exports.setdefault(module, {}).update({m.name: m.id for m in members})
```

For a file with two+ same-named callables, `exports[module][name]` ends up being
**whichever same-named member `store.neighbors()` returns last**. That physical
order is not stable across builds: an incrementally-updated file is `DETACH
DELETE`d and re-inserted on refresh, giving a different Kuzu row order than a file
inserted once during a full index — so the last-wins pick flips. The chosen target
is always a real overload of the right function, so node/edge sets stay correct;
only *which* instance the CALLS edge points at changed.

## Fix

Sort the CONTAINS members by node id before building the name→id maps, making the
selection deterministic regardless of store iteration order:

```python
members = sorted(
    await store.neighbors(f.id, [EdgeKind.CONTAINS], depth=1),
    key=lambda m: m.id,
)
```

This also stabilizes the namespace FQN / namespace-prefix indexes built from the
same `members` list (PHP/Java/C#).

## Verification

- **Real repo:** re-ran the click incremental-vs-full experiment; the graphs are
  now byte-identical modulo `prov_commit` (an unchanged file legitimately keeps
  the commit at which it was last parsed — explicitly out of the feat-004 contract
  scope). 1964 nodes / 2732 edges, zero structural differences.
- **Regression guard:** `tests/ingest/test_resolver.py::
  test_overload_resolution_is_order_independent` resolves the same overloaded
  fixture through a store wrapper that reverses `neighbors()` order and asserts the
  CALLS target is identical (fails without the fix, passes with it).
- **Coverage:** `tests/ingest/incremental/test_equivalence.py` fixtures gained a
  same-named-callable module + caller (the prior fixtures had none — which is why
  this slipped past the property test).

## Notes

This was invisible to the existing feat-004 property test because its fixtures had
no same-named definitions, and invisible to small fixtures generally: the Kuzu
row-order divergence only shows up at scale (here, ~1900 nodes). Found by an
end-to-end incremental-vs-full graph diff on a real repository during pre-release
validation — the kind of check the unit property test approximates but cannot
fully reproduce.
