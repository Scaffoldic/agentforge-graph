---
name: Bug report
about: Something the engine, CLI, or MCP server got wrong
title: "[bug] "
labels: bug
---

## What happened

A clear description of the bug, and what you expected instead.

## Reproduce

Steps / the smallest repo or snippet that triggers it:

```bash
ckg index .
ckg ...        # the command that misbehaves
```

If it's an extraction/resolution issue, a **minimal source file** that reproduces
it helps a lot.

## Environment

- agentforge-graph version: `ckg --version` (or `pip show agentforge-graph`)
- Python version:
- OS:
- Store backend (if not default): `kuzu`/`neo4j`/`pgvector`/`surrealdb`/…
- Language(s) involved (if extraction): Python / TS / Go / …
- Provider (if embed/enrich): `bedrock`/`openai`/`anthropic`/`fake`/…

## Logs / output

```
paste the relevant output, error, or stack trace
```

## Notes

Anything else — was it incremental vs full index, a specific framework pack, etc.
