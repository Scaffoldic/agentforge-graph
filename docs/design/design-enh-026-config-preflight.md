# design-enh-026: fail-fast config preflight + `ckg doctor`

Mirrors [ENH-026](../enhancements/ENH-026-config-preflight-fail-fast.md).

## Goal

Catch a misconfigured driver (optional extra not installed) or missing
credential **before** any indexing/embedding work, and print the exact fix —
instead of a raw `ModuleNotFoundError` thrown deep in a run.

## Module: `agentforge_graph/preflight.py` (engine-shared, framework-free)

Single source of truth: `_REQUIREMENTS: driver → (probe_module, pip_extra)`.
A driver absent from the table is a base driver (`fake`/`scripted`/`kuzu`/
`lancedb`/`anthropic`) needing no extra. `_KEY_ENV: driver → api-key env var` for
the credentialed drivers (`openai`/`voyage`/`anthropic`); Bedrock is intentionally
absent (its AWS chain is resolved by boto3 at call time, not a single env var).

Probes are **import-light** — `importlib.util.find_spec` and `os.environ`, never a
live model call — so the gate is cheap and deterministic.

Public surface:
- `missing_extra(driver) -> (module, extra) | None` — the table lookup + probe.
- `install_command(extra) -> "pip install 'agentforge-graph[extra]'"`.
- `ProviderUnavailable(ImportError)` + `ensure_installed(driver, role)` — the
  typed, install-command-bearing error the in-process path can opt into.
- `Problem(scope, severity, summary, fix)` — one issue with its fix.
- `check_embedder / check_enrich / check_store` (respect `embed.enabled` /
  `enrich.enabled` per ENH-023) and `preflight(config, scope, *, embed, enrich,
  store)` — aggregates only the roles a run will exercise.

## CLI wiring (`cli.py`)

- `_print_problem(p)` renders `✗/⚠ [scope] summary` + `fix:` line.
- `_preflight_or_exit(args, *, embed, enrich)` resolves config, runs `preflight`,
  prints problems, returns True (→ exit 2) on any error. Wired at the **top** of
  `_index` (embed=args.embed), `_embed` (embed=True), `_enrich` (enrich=True),
  after the read-only check and **before** opening the store.
- New `ckg doctor [path] [--config] [--workspace]` (`_doctor`) — validates
  readiness without indexing; `--workspace` resolves each member's config
  (ENH-022 cascade) and reports **all** members' problems in one pass.

## Resolved decisions

| Decision | Rationale |
|---|---|
| Gate scoped to the verb; doctor checks all roles | `ckg index` (no `--embed`) shouldn't demand embed creds; `doctor` shows full readiness. |
| In-process guard *not* at builder construction | `embedder_from_config` must stay constructible for metadata without the SDK (OpenAIEmbedder lazy client) — a tested contract. `ensure_installed` is opt-in API. |
| Creds: error for openai/voyage/anthropic; none for bedrock | Those need a single env var; the AWS chain is multi-source and resolved by boto3 — left to runtime / `doctor --live` (future). |
| Probe with `find_spec`, not import | Cheap, side-effect-free, deterministic; a live connectivity check is a separate opt-in. |

## Out of scope (noted)

- Live connectivity checks (`doctor --live`): a real Bedrock/OpenAI ping. Future.
- Wiring `ensure_installed` into every SDK-import site (fragile vs. monkeypatched
  fakes in tests). The CLI preflight is the primary fail-fast path.

## Chunk plan (as built)

1. `preflight.py`: requirement table, probes, `ProviderUnavailable`,
   `ensure_installed`, `Problem`, `check_*`, `preflight`.
2. CLI gate (`_preflight_or_exit`) on index/embed/enrich + `_print_problem`.
3. `ckg doctor` (single + `--workspace`, all-at-once).
4. Tests (`test_preflight.py`): table/install-command, missing/present probes
   (monkeypatched → env-independent), per-role checks incl. ENH-023 disabled
   skips, CLI gate refuses before work, `ckg doctor` clean vs. problems.

Gate: 819 passed, 94.83% cov, mypy + ruff clean.
