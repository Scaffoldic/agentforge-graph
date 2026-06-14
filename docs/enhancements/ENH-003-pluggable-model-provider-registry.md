# ENH-003: Pluggable model-provider registry (consumer choice of LLM/embeddings)

| Field | Value |
|---|---|
| **ID** | ENH-003 |
| **Value/Impact** | High (OSS adoption — most consumers are not on Bedrock) |
| **Effort** | M |
| **Status** | done — phase 1 (registry seam) + phase 2 (first-party non-Bedrock adapters) |
| **Area** | `embed`, `enrich`, `config` |
| **Relates to** | feat-005 (embeddings), feat-012 (enrichment); mirrors `store/registry.py` |

## Motivation

The model layer is already **injectable** (`Embedder`, `PatternJudge`,
`Summarizer` interfaces — ADR-style seam). But the only **shipped** live adapters
are AWS Bedrock (Claude + Cohere). A consumer who runs on the Anthropic API,
OpenAI, or a local model can't *select* a provider from config — they'd have to
construct an adapter in code. For an open-source release where most users are
**not** on Bedrock, "bring your own provider" needs to be a config line, not a
code change.

## Current behavior

- Embeddings: `embed.driver: bedrock | fake` resolved by a small if/else in
  `embed/registry.py` (`embedder_from_config`). Only two drivers.
- Enrichment: `CodeGraph.enrich/summarize` **hard-construct** `BedrockClaudeJudge`
  / `BedrockClaudeSummarizer` from `enrich.model` (a Bedrock id). No provider
  selection; no registry; no non-Bedrock adapter.

## Proposed change

Mirror the **storage driver registry** (`store/registry.py`, entry-point groups)
for models:

1. **Provider registry** for each role with entry-point groups
   (`agentforge_graph.embedder_providers`, `…judge_providers`,
   `…summarizer_providers`) + built-ins. Config selects by name:
   ```yaml
   embed:  { driver: bedrock }          # bedrock | openai | fake | <entry-point>
   enrich: { provider: bedrock, model: us.anthropic.claude-haiku-4-5-... }
   ```
2. **A couple of first-party adapters beyond Bedrock**, at minimum:
   - an **Anthropic-API** judge/summarizer (reuse `agentforge-anthropic`, so it
     rides the framework Agent path where that fits), and
   - an **OpenAI** embedder + judge (the most-requested non-AWS path).
3. Keep the `Scripted*`/`Fake*` adapters as the CI/default-offline drivers.
4. `enrich` builds the judge/summarizer via the registry instead of hard-calling
   Bedrock; `embedder_from_config` becomes a registry lookup.

## Acceptance criteria

- A consumer selects embeddings **and** enrichment providers entirely from
  `ckg.yaml` (no code), including a non-AWS path end-to-end.
- Third-party providers install as `pip install + entry point` with no core
  change (same ergonomics as storage drivers).
- CI stays model-free (fakes are just another registered driver); each live
  adapter has an env-gated test.

## Status — what shipped

**Phase 1 (done, `enh/003-…`):** the registry *seam*.

- `providers.py` — generic `resolve_provider` (built-in → entry-point → error).
- `embed/registry.py` — `embedder_from_config` is registry-backed; group
  `agentforge_graph.embedder_providers`.
- `enrich/registry.py` — `judge_from_config` / `summarizer_from_config`; groups
  `agentforge_graph.{judge,summarizer}_providers`; new `scripted` credential-free
  built-in; Bedrock lazy.
- `EnrichConfig.provider` selects judge + summarizer (default `bedrock` — no
  behaviour change). `codegraph.enrich/summarize` build via the registry.
- Tests prove third-party providers resolve via entry point with **no core
  change** — the pluggability guarantee. CI stays model-free.

This makes "BYO provider" / "pick your provider from config" in the README/ARCH
literally true: a third party adds a provider by `pip install` + one entry point.

**Phase 2 (done, `enh/003-phase-2-non-bedrock-adapters`):** first-party non-Bedrock
adapters — non-AWS users are now batteries-included.

- `enrich/claude.py` — provider-neutral `ClaudeJudge` / `ClaudeSummarizer` + a
  `ClaudeClient` protocol. Bedrock's `invoke_model` and the direct Anthropic API
  return the same Messages shape, so prompts/parsing/cost/budget are shared and
  only the transport differs. `BedrockClaude{Judge,Summarizer}` became thin
  subclasses (public constructors preserved).
- `enrich/anthropic{,_client}.py` — **Anthropic-API** judge/summarizer over the
  `anthropic` SDK (ships in the base install, no extra). `api_model_id()`
  normalises the Bedrock inference-profile id to the bare API id, so the default
  `enrich.model` works unchanged. `enrich.provider: anthropic` selects both roles.
- `embed/openai.py` — **OpenAI** embedder (`openai` extra, lazy). `embed.base_url`
  points the same driver at any OpenAI-compatible local server (Ollama/vLLM/LM
  Studio), so "run it locally" is also config-only.
- Config: `embed.{base_url,api_key_env}`, `enrich.{base_url,api_key_env}`;
  registries gained the `openai` / `anthropic` built-ins.
- Decision: adapters call the SDKs **directly** (not via the framework `Agent`)
  to keep forced-tool + cost parity with the Bedrock path and reuse the shared
  `ClaudeJudge`/`ClaudeSummarizer` core.
- Env-gated live tests `CKG_LIVE_ANTHROPIC` / `CKG_LIVE_OPENAI`; CI stays
  model-free. Developer-facing guide: `docs/guides/model-providers.md`.

The last acceptance bullet (a non-AWS path end-to-end with a live adapter) is met.

## Notes / alternatives

If the framework grows a Bedrock provider + an embedding-provider contract (see
`docs/framework/2026-06-13-framework-support-wishlist-providers.md`), some of our
adapters can be dropped in favour of `provider:model` strings. This ENH is
forward-compatible with that.
