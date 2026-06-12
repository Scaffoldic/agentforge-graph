# Testing standards — agentforge-graph

- **Runner:** `pytest`, async via `pytest-asyncio` (`asyncio_mode =
  auto` — no per-test marker needed). Run: `uv run pytest`.
- **Coverage floor: 90%** on `agentforge_graph.core` (and each
  feature's package as it lands). Enforced by `--cov-fail-under=90`.
- **Conformance suites** (`core/conformance.py`) are the contract tests:
  every `GraphStore` adapter (feat-003) and `Extractor` (feat-002/011)
  subclasses the matching base class and provides its fixture. A new
  backend is "done" when the shared suite passes against it.
- **Property/determinism tests** for anything identity-related: symbol
  IDs round-trip and are order-independent; extraction is deterministic
  (same content → same subgraph).
- **No network / no model calls in unit tests.** LLM-touching paths
  (feat-010/012) use recorded/mocked responses; live tests are
  env-gated and excluded from the default run.
- Test fixtures use builders (`make_sample_subgraph`), not copy-pasted
  literals.
