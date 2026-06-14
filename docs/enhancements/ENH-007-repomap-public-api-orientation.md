# ENH-007: bias the repo map toward the public API for orientation

| Field | Value |
|---|---|
| **ID** | ENH-007 |
| **Value/Impact** | Medium (the repo map's whole job is "orient me fast") |
| **Effort** | S–M |
| **Status** | proposed |
| **Area** | `repomap` |
| **Relates to** | feat-007 (budget-aware repo map) |

## Motivation

On `pallets/click` (W1 validation), `ckg map --budget 1500` filled the budget
with private `_compat.py` helpers (`_force_correct_text_stream`, `isatty`, …)
before any of the public API. The public classes (`Command`, `Context`,
`Option`, `Group`) only appear once the budget is raised (~4000).

This is *defensible* by PageRank — `_compat` is imported widely, so it scores
high centrality — but it's poor **orientation**: a developer (or agent) asking
"what is this codebase" wants `Command`/`Context`/`Group` first, not stdout
stream shims.

## Current behavior

`repomap` ranks symbols by personalized PageRank over the edge graph
(provenance-weighted), filtered to `kinds: [Class, Function, Method]`, then
renders within the token budget. Centrality is the only ranking signal; there is
no notion of "public/exported" vs "private/internal".

## Proposed change

Add a light **public-API bias** to the ranking (tunable, not a hard filter):

- Down-weight clearly-private symbols: leading-underscore names, and modules
  whose name starts with `_` (`_compat`, `_winconsole`, `_termui_impl`).
- Optionally up-weight symbols re-exported from the package root (`__init__.py`
  `__all__` / `from .x import y as y`) — the de-facto public surface.
- Keep it a weight, not a filter (private hubs can still appear when genuinely
  central), and expose a `repomap.public_bias` knob (mirrors ENH-001's
  `conservative|broad` tuning style).

## Acceptance criteria

- On click at a small budget, the map surfaces the public API
  (`Command`/`Context`/`Group`/`Option`) before private `_`-prefixed internals.
- Behavior is tunable and defaults sensibly; pure-centrality remains available.
- A fixture asserts the ordering shift on a repo with a clear public/private
  split.

## Notes

Pairs naturally with a future "summary-first" map mode (feat-012 summaries) for
even better orientation. Low risk; improves the first thing a new consumer sees.
