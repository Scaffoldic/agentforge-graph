# Coding standards — agentforge-graph

- **Python 3.13**, `from __future__ import annotations` in every module.
- **Type everything.** `mypy --strict` is the gate (`uv run mypy`).
  No untyped defs, no implicit `Any` in the engine core.
- **Value types are Pydantic models**, validated at construction —
  that's where ADR-0004 (provenance) and ADR-0003 (symbol-id) rules are
  enforced. Frozen where the value is an identity (`Provenance`,
  `SourceFile`, `ParsedSymbol`).
- **Layering (ADR-0001):** the deterministic engine core
  (`core`/`ingest`/`store`/`retrieve`) must not import `agentforge`.
  Enforced by a unit test. Framework rails are used only at the
  serving/enrichment edges.
- **Lint/format:** `ruff` (`uv run ruff check` + `ruff format`),
  line length 100.
- **No `print`** in library code; surface results via return values /
  logging.
- Public surface of a package is its `__init__.__all__`; internal module
  moves must not break that surface.
