# ENH-003: Pluggable model-provider registry (consumer choice of LLM/embeddings)

| Field | Value |
|---|---|
| **ID** | ENH-003 |
| **Value/Impact** | High (OSS adoption — most consumers are not on Bedrock) |
| **Effort** | M |
| **Status** | proposed |
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

## Notes / alternatives

If the framework grows a Bedrock provider + an embedding-provider contract (see
`docs/framework/2026-06-13-framework-support-wishlist-providers.md`), some of our
adapters can be dropped in favour of `provider:model` strings. This ENH is
forward-compatible with that.
