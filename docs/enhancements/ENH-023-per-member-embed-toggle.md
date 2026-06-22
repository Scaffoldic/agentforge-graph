# ENH-023: per-member embed enable/disable

| Field | Value |
|---|---|
| **ID** | ENH-023 |
| **Value/Impact** | Medium (makes the workspace build know what to vectorize) |
| **Effort** | S |
| **Status** | proposed |
| **Area** | `config`, `cli`, `serve/workspace` |
| **Relates to** | [THEME: org-central-knowledge](THEME-org-central-knowledge.md), ENH-021 (build commands), ENH-022 (cascade) |

> **One-liner.** A first-class `embed.enabled` config key (and per-member
> `embed: true|false` in `workspace.yaml`) so `ckg build --workspace` knows which
> repos to vectorize — instead of "disable" meaning *don't run the command* or
> *use the fake driver*.

## Motivation

Semantic search (`ckg_search`) costs money and credentials (Bedrock/OpenAI). In a
workspace some repos warrant vectors and some don't (a tiny config repo, a
third-party dependency cloned for structure only). The single build command
(ENH-021) needs a **declarative** signal per member for whether to embed — there
is no such switch today.

## Current behavior

- There is **no `embed.enabled` flag**. `EmbedConfig` (`config.py:150-165`) has
  `driver`/`model`/`region`/`dim`/`batch_size`/`assume_role_arn`/`base_url`/
  `api_key_env` — but no on/off.
- The only ways to "not embed" are operational, not declarative: **skip** the
  `ckg embed` command, omit `--embed` on `ckg index`, or set `driver: fake`
  (a deterministic no-op meant for CI/offline). None of these compose with a
  one-command workspace build.

## Proposed change

Two additive surfaces, both honoring the ENH-022 cascade.

### 1. `embed.enabled`

```yaml
embed:
  enabled: true            # default true (preserves today's behavior when embed runs)
  driver: bedrock
```

When `false`, `ckg embed`/`ckg build` **skip** the embed step for that scope and
say so (not an error). `ckg index --embed` likewise honors it.

### 2. Per-member shorthand in `workspace.yaml`

```yaml
members:
  - name: app
    repo: ../app
  - name: vendor-lib
    repo: ../vendor-lib
    embed: false           # structure only — no vectors, no creds needed
```

The member shorthand is sugar for `embed.enabled: false` in that member's
resolved config (ENH-022 precedence applies).

### 3. Interaction with preflight

ENH-026 preflight only checks embedder driver/creds for members where embed is
**enabled** — so a workspace of mostly structure-only repos doesn't demand
Bedrock creds it never uses.

## Implementation sketch

- `EmbedConfig` gains `enabled: bool = True` (`config.py`).
- `WorkspaceMember` gains `embed: bool | None = None` (`serve/workspace.py`),
  folded into the member's resolved `embed.enabled` by the ENH-022 cascade.
- The embed step in `ckg embed`/`ckg build`/`ckg index --embed` checks
  `cfg.embed.enabled` and skips with a logged reason when false.

## Surfaces

- `embed.enabled` config key.
- `embed: true|false` per-member shorthand in `workspace.yaml`.
- Build/report output shows `embed: skipped (disabled)` for those members.

## Suggested chunk plan (one branch, multiple commits)

1. `EmbedConfig.enabled` + honor it in the embed code path; tests (enabled vs.
   disabled → no vectors written, no provider constructed).
2. `WorkspaceMember.embed` shorthand → cascade into `embed.enabled`; tests.
3. Wire into ENH-021 build/report + ENH-026 preflight gating; docs.

## Acceptance criteria

- `embed.enabled: false` (or member `embed: false`) → `ckg build` writes the
  graph but **no vectors**, and the embedder provider is never constructed (so no
  creds required for that member).
- Default (`enabled` unset) behaves exactly as today when embed is run.
- Preflight skips embedder checks for members with embed disabled.

## Notes / alternatives / risks

| Concern | Note |
|---|---|
| Redundant with `driver: fake`? | No — `fake` writes deterministic junk vectors (CI). `enabled: false` writes **nothing** and constructs no provider; semantically "this repo has no semantic search." |
| Default value | Default `true` so existing `ckg embed` runs are unchanged; the flag's job is to let a workspace turn it **off** selectively. |

## 0.6.0 candidacy

Small companion to ENH-021/022 — the declarative switch the workspace build reads.
Land alongside them.
