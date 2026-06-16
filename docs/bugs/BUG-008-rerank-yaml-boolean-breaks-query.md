# BUG-008: `rerank: off` in the shipped ckg.yaml breaks `ckg query`

| Field | Value |
|---|---|
| **ID** | BUG-008 |
| **Severity** | High |
| **Status** | fixed (`bug/008-rerank-yaml-boolean`) |
| **Found** | 2026-06-16 (pre-0.1 validation item 4 — server-backend e2e on `pallets/itsdangerous`) |
| **Fixed** | 2026-06-16 — `field_validator(mode="before")` on `RetrieveConfig.rerank` coerces YAML booleans (`off`→`"off"`, `on`→`"lexical"`). |
| **Area** | `config` (`RetrieveConfig`) |
| **Affects** | feat-006 retrieval — **every `ckg query` / `CodeGraph.retrieve()` with the default config**, plus `serve-mcp` search tools |

## Summary

The shipped `ckg.yaml` sets `retrieve.rerank: off`. YAML 1.1 parses bare `off`
(and `on`/`yes`/`no`/`true`/`false`) as a **boolean**, so the value arrives as
Python `False`, but `RetrieveConfig.rerank` is typed `str` → pydantic rejects it
and `RetrieveConfig.load` raises `StoreConfigError`. Any retrieval path that loads
the default config therefore fails:

```
StoreConfigError: invalid retrieve config in ckg.yaml: 1 validation error for
RetrieveConfig
rerank
  Input should be a valid string [type=string_type, input_value=False, input_type=bool]
```

This is a **default-config, core-command** break: `ckg query` does not work out of
the box (and neither do the `serve-mcp` search tools when they load `ckg.yaml`).

## Reproduce

```bash
ckg query --path <repo> "any question"
# ... StoreConfigError: invalid retrieve config in ckg.yaml: rerank ... input_value=False
```

or directly:

```python
from agentforge_graph.config import RetrieveConfig
RetrieveConfig.load("ckg.yaml")   # raises StoreConfigError
```

## Root cause

`rerank` was added (ENH-009) as a free `str = "off"`. The shipped config writes it
unquoted (`rerank: off`), and `yaml.safe_load` returns `False` for it. The retrieval
tests never caught this because they construct `RetrieveConfig(...)` directly or use
fixture configs with `rerank: lexical` (a string YAML keeps) — none loaded the
shipped `rerank: off` through YAML.

## Fix

A `before` field validator coerces YAML booleans back to the canonical reranker
modes, so both the shipped config and any user's `rerank: off`/`on` work:

```python
@field_validator("rerank", mode="before")
@classmethod
def _coerce_rerank(cls, v: Any) -> Any:
    if isinstance(v, bool):
        return "lexical" if v else "off"   # off -> disabled, on -> the only enabled mode
    return v
```

`reranker_from_config` then resolves `"off"` → `NoopReranker` (the intended
default). `on`/`true` map to `"lexical"` (the single enabled mode), which is the
least-surprising reading of "turn the reranker on".

## Verification

- `RetrieveConfig.load("ckg.yaml")` now returns `rerank="off"`; `ckg query` runs
  end-to-end (validated on the item-4 Neo4j + pgvector pipeline — pgvector search →
  neo4j expansion returned the expected `signer.py` signing methods).
- **Regression guard** `tests/test_config.py`: loads the *shipped* `ckg.yaml` (would
  have caught this directly) and parametrizes `off`/`on`/`lexical`/`"off"`/`false`/
  `true`. Fails on the boolean cases without the validator.

## Notes

Other `str` config fields that can legitimately receive a YAML-ambiguous token
(`frameworks.enabled` accepts `off`) are typed `str | list[str]` and already
tolerate the bool, or are always quoted/enumerated in the shipped config. `rerank`
was the only `str`-typed field whose shipped value is a bare YAML boolean.
