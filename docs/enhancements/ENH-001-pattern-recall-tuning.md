# ENH-001: Improve pattern-tag candidate recall

| Field | Value |
|---|---|
| **ID** | ENH-001 |
| **Value/Impact** | Medium |
| **Effort** | M |
| **Status** | done |
| **Area** | `enrich.heuristics` |
| **Done** | 2026-06-13 (`enh/e2e-eval-enhancements`) — (1) **base-class signal**: a class is nominated by applying the role-suffix rules to its base classes (parsed from the signature, no INHERITS edges needed), so a subclass of a role-named ABC is caught even without a matching own-name; (2) **`enrich.patterns_recall: conservative\|broad`** — broad adds Manager/Provider/Gateway/Client suffixes, a lower CRUD threshold, and "implements a non-trivial ABC → Strategy". On this repo, broad raises candidates 10 → 21; conservative stays precise. |
| **Relates to** | feat-012 (pattern tagging) |

## Motivation

On the dogfood run the stage-1 heuristics nominated only **10 of 125 classes**;
2 were tagged. Precision was excellent (the judge correctly rejected the rest),
but recall is low: real patterns with no name-suffix signal are never nominated,
so the judge never sees them. E.g. `LanceVectorStore` (a Repository-shaped
adapter) and the `*Pipeline` classes (Service-shaped) were not candidates.

This is **not a bug** — the two-stage design deliberately favours precision and
low cost (heuristics nominate, the LLM confirms). It's a tunable recall knob.

## Current behavior

`PatternHeuristics._class_patterns` (`enrich/heuristics.py`) nominates mostly on
**name suffix** (`*Repository/*Service/*Controller/*Factory/…`) plus a few shape
rules (CRUD method names, `get_instance`, observer-ish methods, data-only
classes). Classes whose role is structural but unnamed (e.g. an interface
implementation that abstracts storage) aren't nominated.

## Proposed change

Add structural signals that don't depend on naming, while keeping nomination
cheap and the judge as the precision gate:

- **Interface-implementation:** a class that `IMPLEMENTS`/`INHERITS` an ABC and
  overrides its methods → nominate the role of that ABC family (e.g. a
  `*Store`/`*Repository` base → Repository; a `Pipeline`/`run()` shape →
  Service).
- **Adapter shape:** a class wrapping a single external dependency (one injected
  client, methods delegating to it) → Adapter.
- **Strategy shape:** sibling classes implementing the same small interface →
  Strategy.
- Make the suffix/shape tables and a `min_methods`/recall toggle configurable
  (`enrich.patterns.recall: conservative|broad`).

## Acceptance criteria

- On a labelled fixture repo, stage-1 recall improves materially with no drop in
  final (post-judge) precision.
- Cost stays bounded (judge calls remain a small fraction of classes; report the
  candidate count so the broadening is visible).

## Notes / alternatives

Broader nomination = more judge calls = more cost; gate behind config and keep
`conservative` the default. An LLM-only nomination pass is explicitly *not* the
direction (cost + the spec's two-stage rationale).
