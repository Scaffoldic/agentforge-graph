# design-enh-022: workspace-level config cascade

Mirrors [ENH-022](../enhancements/ENH-022-workspace-config-cascade.md). The *how*:
resolved decisions, file layout, types, chunk plan.

## Goal

One config block at the workspace level supplies defaults every member inherits,
with deterministic per-member override — so the operator configures the org once.

## Key insight: there is no single `EngineConfig`; everything funnels through `_read_block`

Every engine config block is read lazily and independently:

```python
StoreConfig.load(self._config)   # → _read_block(StoreConfig, "store", self._config)
EmbedConfig.load(self._config)   # → _read_block(EmbedConfig, "embed", self._config)
```

…and `self._config` is a **file Path** threaded through `CodeGraph`/`Engine`
(`ingest/codegraph.py`, `serve/engine.py`). `_read_block` (`config.py:66`) is the
**single chokepoint**: it opens the file, extracts the section (`app:` for
`agentforge.yaml`, top-level for `ckg.yaml`), and validates one block.

**Decision:** make the threaded `config` *polymorphic* — a `Path` **or** an
in-memory `ResolvedConfig` carrying a pre-merged section dict. Then **every**
`X.load(config)` call site reads the merged config transparently, with no change
to the ~40 call sites. The cascade only has to (a) build the merged section dict
per member and (b) teach `_read_block` + `resolve_config` to accept it.

## Resolution order (lowest → highest precedence)

For each member, the effective section dict is a **per-block shallow merge** (a
later source fully replaces a block; it does not deep-merge keys):

1. built-in defaults — implicit (a block absent from the section → its model
   defaults).
2. **sibling `ckg.yaml`** next to `workspace.yaml` — fallback defaults source.
3. **workspace `defaults:`** block in `workspace.yaml` — org-wide defaults (wins
   over the sibling, per ENH-022 note).
4. **member inline overrides** — recognized block keys on the member entry
   (`store:` / `embed:` / …).
5. **member `config:` file** — the explicit per-repo file, highest precedence.

## Types & files

### `config.py` (the chokepoint)

```python
class ResolvedConfig:
    """An already-merged engine config section (block-key → block-dict), an
    in-memory drop-in for a config file path. Threaded through the engine exactly
    like a Path; read by `_read_block`."""
    section: dict[str, Any]
    origin: str = "<resolved>"   # for error messages

ConfigSource = str | Path | ResolvedConfig | None
```

- `_read_block(model, key, config)`: if `config` is a `ResolvedConfig`, validate
  `config.section.get(key) or {}` (raise `StoreConfigError` on invalid, naming
  `config.origin`); else behave exactly as today (None/Path).
- `resolve_config(config, repo_path)`: **pass a `ResolvedConfig` through
  unchanged** (it is already resolved); else today's discovery.
- `_section_of(path) -> dict`: factor the existing `app:`-vs-top-level extraction
  out of `_read_block` so the cascade reuses it for member files / sibling
  `ckg.yaml` (strict: raise `StoreConfigError` on malformed YAML).

### `serve/workspace.py` (the cascade)

- `WorkspaceMember`: `model_config = ConfigDict(extra="allow")` so inline block
  overrides (`store:`/`embed:`/…) are captured in `model_extra`. A helper
  `member_overrides(m) -> dict` returns the subset of `model_extra` whose keys are
  known engine block keys (the `_Block.KEY` set) **and** whose value is a mapping.
  (ENH-023 will extend this for the `embed: bool` shorthand.)
- `WorkspaceConfig`: add `defaults: dict[str, Any]` (raw `defaults:` block) and,
  at `load()`, discover a sibling `ckg.yaml` next to the manifest → its section as
  the fallback defaults.
- `resolve_member_config(ws, m) -> ResolvedConfig`: layer sources 2→5 per the
  order above into one section dict; return `ResolvedConfig(section=…,
  origin=f"workspace:{m.name}")`.

## Known block keys

The merge needs the set of recognized block keys. Source of truth: the `KEY`
class-var on each `_Block` subclass. Add `config.block_keys() -> set[str]`
(collect `KEY` from `_Block.__subclasses__()`), so new blocks are picked up
automatically and `member_overrides` doesn't drift.

## What this ENH does *not* do

- It does **not** add `--workspace` to the write verbs or `ckg build` — that's
  ENH-021, which calls `resolve_member_config` per member and passes the
  `ResolvedConfig` into `CodeGraph.open(repo, config=resolved)`.
- It does **not** add the `embed: bool` shorthand — that's ENH-023 (extends
  `member_overrides`).

This ENH ships the **machinery + tests**: the polymorphic config source and the
resolver, proven by unit tests and one integration test that opens a `CodeGraph`
with a `ResolvedConfig`.

## Chunk plan

1. `ResolvedConfig` + `_section_of` factor-out + `_read_block`/`resolve_config`
   accept it + `block_keys()`. Unit tests: read each block from a `ResolvedConfig`;
   passthrough; malformed section errors with origin.
2. `WorkspaceMember` extra-capture + `member_overrides`; `WorkspaceConfig.defaults`
   + sibling-`ckg.yaml` discovery. Tests: parse `defaults:`, capture inline
   overrides.
3. `resolve_member_config` precedence (each rung) + per-block shallow-merge
   semantics. Unit tests at every precedence rung.
4. Integration: open a `CodeGraph` (or just `StoreConfig.load`) from a
   `ResolvedConfig` and confirm the merged values win; regression that a lone repo
   (path config) is byte-for-byte unchanged.

## Acceptance (from the ENH)

- `defaults:` applies to every member lacking its own config.
- member inline / `config:` file overrides win for that member only.
- a repo outside any workspace resolves config exactly as today.
- precedence covered by tests at each rung.

## Risks / decisions

| Decision | Rationale |
|---|---|
| Per-block shallow merge (not deep) | Predictable; matches the block model; documented. |
| `ResolvedConfig` over temp files | Spec requires no temp files; keeps secrets/env-refs in memory. |
| Inline `defaults:` > sibling `ckg.yaml` | One authoritative source; sibling is convenience fallback. |
| Polymorphic `config` at `_read_block` | Smallest blast radius — ~40 call sites unchanged. |
