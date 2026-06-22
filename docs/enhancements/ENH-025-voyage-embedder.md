# ENH-025: first-party Voyage embedder (upstream first, then implement)

| Field | Value |
|---|---|
| **ID** | ENH-025 |
| **Value/Impact** | Medium (strong code-embedding option: `voyage-code-*`) |
| **Effort** | S (our adapter) + upstream dependency |
| **Status** | deferred — raise upstream first |
| **Area** | `embed/registry`, upstream `agentforge-py` |
| **Relates to** | ENH-003 (pluggable provider registry), [model-providers guide](../guides/08-model-providers.md) |

> **One-liner.** Add Voyage (`voyage-code-3` etc.) as an embedding option. Per the
> 0.6 scope decision: **first raise Voyage support with the framework
> (agentforge-py) upstream**, then implement our embedder adapter on top once the
> framework rail lands. Not built in the 0.6 epic.

## Motivation

Voyage's code-specialized embedding models (`voyage-code-3`) are competitive for
code retrieval and a credible alternative to Bedrock/OpenAI for consumers who
prefer them. The user named Voyage explicitly as a desired driver.

## Current behavior

- Built-in embedder drivers are `{fake, bedrock, openai}`
  (`embed/registry.py:56-60`). **No `voyage` driver.**
- Voyage is **not** on Bedrock (`embed/bedrock.py:6`), so it isn't reachable via
  the bedrock path. Today it would require a third-party plugin registered under
  the `agentforge_graph.embedder_providers` entry point (ENH-003 supports this).

## Plan (two steps, the first is a dependency)

### 1. Raise Voyage support upstream (agentforge-py) — do this first

File an enhancement request on agentforge-py to provide a Voyage provider rail at
the framework level (mirroring how the framework already offers model/embedding
rails), so our engine can reuse it rather than each consumer reinventing it. This
follows the same "surface it upstream" pattern as ENH-017. Track the upstream
issue number here once filed.

### 2. Implement our adapter (after the upstream rail exists)

Add a `voyage` builtin to the embedder registry — a thin `VoyageEmbedder`
implementing the `Embedder` interface (`embed/base.py`), reading `api_key_env`
(default `VOYAGE_API_KEY`), behind a `[voyage]` extra. Config:

```yaml
embed:
  driver: voyage
  model: voyage-code-3
  dim: 1024
  api_key_env: VOYAGE_API_KEY
```

It must also be covered by ENH-026 preflight (importable? `VOYAGE_API_KEY` set?).

## Acceptance criteria (when implemented)

- `embed.driver: voyage` produces real vectors via the Voyage API behind a
  `[voyage]` extra; offline contract test with a fake client; env-gated live smoke.
- ENH-026 preflight reports Voyage availability + credential status.

## Notes / status

- **Deferred from the 0.6 epic** by decision: raise the framework request first,
  implement our end afterward. Kept as a tracked spec so it isn't lost.
- Until then, the OpenAI-compatible / third-party-plugin path (ENH-003) remains
  the way to use Voyage without a core change.
