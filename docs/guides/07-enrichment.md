# LLM enrichment — design-pattern tags & module summaries

> **TL;DR:** Add LLM-derived design-pattern tags and bottom-up module summaries —
> budgeted, every fact carrying `llm` provenance + a confidence. `ckg enrich`
> (Bedrock Claude by default; `--budget-usd` caps spend).

Beyond parsed structure, agentforge-graph can add a layer of **LLM-derived
meaning**: design-pattern tags (*"this class is a Repository"*) and bottom-up
module summaries — every fact carrying `llm` provenance, a confidence, and a
rationale (feat-012). It is **explicit and budgeted**: nothing calls a model
unless you run `ckg enrich`.

## Run it

```bash
ckg enrich . --all --budget-usd 2        # tags + summaries, hard $ ceiling
ckg enrich . --tags --budget-usd 1       # just pattern tags
ckg enrich . --summaries                 # just module summaries
ckg enrich . --decisions                 # infer GOVERNS for unlinked ADRs (feat-010)
```

Then query the derived facts:

```bash
ckg tagged Repository                    # symbols tagged with a design pattern
ckg summaries --scope src/payments/      # module summaries for a subtree
```

Over **MCP**, the `ckg_explain` tool returns a symbol's tags + 1-hop facts as JSON.

## Configure

```yaml
# ckg.yaml
enrich:
  enabled: on
  provider: bedrock        # bedrock | anthropic | scripted | <entry-point>
  budget_usd: 5            # default ceiling; --budget-usd overrides per run
  confidence_floor: 0.6    # drop tags below this confidence
```

## Budgets & provenance

- **A hard ceiling.** The budget is enforced by a breaker that checks before each
  call; once spent, enrichment stops cleanly (overrun bounded to one in-flight
  call). Set it per run with `--budget-usd`.
- **Idempotent.** Re-enriching a symbol clears its prior `TAGGED`/`SUMMARIZES`
  edges first, so re-runs don't duplicate.
- **Provenance-tagged.** Every derived node/edge carries `source: llm` +
  confidence — distinguishable from parsed facts, and filterable (a retrieval
  `min_source` floor can exclude LLM facts entirely).

## Offline / CI

Set `enrich.provider: scripted` for a deterministic, credential-free path — that's
what CI uses, so **no model calls or cloud creds are needed to build or test**.
Pick a provider (AWS Bedrock, the direct Anthropic API, or a local
OpenAI-compatible server) per
[`docs/guides/08-model-providers.md`](https://github.com/Scaffoldic/agentforge-graph/blob/main/docs/guides/08-model-providers.md).
