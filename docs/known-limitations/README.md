# Known limitations

Inherent constraints we **acknowledge but won't "fix"** — they come from an
external dependency, a model, or a deliberate design trade-off. Distinct from
bugs (we can fix) and enhancements (we could improve). We record them so they're
not re-filed as bugs and so we can document mitigations.

One file per limitation: `KL-NNN-short-slug.md`. Keep this index current.

## Index

| ID | Title | Category | Status |
|---|---|---|---|
| [KL-001](KL-001-llm-summary-hallucination.md) | LLM summaries/tags can contain small inaccuracies | model-inherent | acknowledged |

## Template

```markdown
# KL-NNN: <title>

| Field | Value |
|---|---|
| **ID** | KL-NNN |
| **Category** | model-inherent / external-dependency / by-design |
| **Status** | acknowledged / mitigated |
| **Area** | package / module |

## Description
What the limitation is.

## Why it's a limitation, not a bug
The inherent/structural reason.

## Mitigation / guidance
How we reduce its impact and what users should expect.
```
