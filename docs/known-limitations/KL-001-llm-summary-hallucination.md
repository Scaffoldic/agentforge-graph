# KL-001: LLM summaries/tags can contain small inaccuracies

| Field | Value |
|---|---|
| **ID** | KL-001 |
| **Category** | model-inherent |
| **Status** | acknowledged (mitigated) |
| **Area** | `enrich` (summaries + pattern tags) |

## Description

LLM-generated text can include minor errors. On the dogfood run, one file
summary rendered the database name as **"Kuzama"** instead of "Kuzu" — the rest
of the summary was accurate. Similarly, a pattern rationale could occasionally
overstate a match.

## Why it's a limitation, not a bug

The output is produced by a probabilistic model (Claude on Bedrock). Occasional
small hallucinations are inherent to generative summarization; we can reduce but
not eliminate them. It is not a defect in our pipeline — the prompt, grounding,
and provenance are working as designed.

## Mitigation / guidance

Already in place:

- **Honest provenance:** every `Summary`/`PatternTag` carries `source="llm"`,
  the `model`, and a `prompt_version`; pattern tags carry a `confidence` and
  `rationale`. Retrieval renders them as `[summary]` / `[llm]`.
- **Opt-out:** `include_llm_facts=False` (feat-006) excludes all LLM-derived
  items from retrieval wholesale.
- **Grounding:** summary prompts instruct the model to summarize only what the
  signatures/names show; tag verdicts must cite structural evidence and clear a
  confidence floor (0.7).

Guidance: treat summaries/tags as **high-quality hints, not ground truth**.
Code structure and parsed/resolved facts remain the authoritative layer. A
stronger model (configurable via `enrich.model`) reduces error rate at higher
cost. Bumping `prompt_version` re-generates stale output on the next `ckg
enrich`.
