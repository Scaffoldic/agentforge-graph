# Architecture decisions — link ADRs & docs to the code they govern

Agents edit code without knowing *why* it's shaped the way it is. agentforge-graph
ingests your **ADRs and docs**, turns each into a `Decision` node, and links it to
the code it `GOVERN`s — so a search hit on `payments/` surfaces *"ADR-0012
(accepted): idempotency keys must be client-side"* **before** the agent changes
anything (feat-010).

## What's ingested

- **ADRs** (`docs/adr/*.md` by default) → `Decision` nodes (id, title, status,
  date) + `GOVERNS` edges to the symbols/paths they mention. `SUPERSEDES` edges
  chain superseded decisions.
- **General docs** (`doc_globs`) → `DocChunk` nodes that `DESCRIBES` the code
  they reference; embedded and retrievable.
- **Docstrings** (Python, JS/TS JSDoc) → `DocChunk` `DESCRIBES` their symbol,
  riding the code file's incremental subgraph.
- **Commit messages** (optional) → `DocChunk`s `DESCRIBES` the files they touched,
  so "why did the retry logic change?" reaches the commit.

Doc/ADR prose is embedded alongside code (tagged `source_type: doc`), so semantic
search finds the *decision*, not just the code — with code weighted over prose by
default to avoid dilution.

## Use it

```bash
ckg index .                                  # ADRs/docs ingested in the same pass

ckg decisions                                # every Decision + what it governs
ckg decisions --status accepted              # filter by status
ckg decisions --scope payments/              # decisions governing a subtree
```

Over **MCP**, the `ckg_decisions` tool returns decisions (status, date, governed
symbols) as JSON; and any `ckg_search` hit expands through `GOVERNS` so the
governing decision rides along with the code.

## Configure

```yaml
# ckg.yaml
knowledge:
  enabled: on
  adr_globs: ["docs/adr/*.md"]      # where your ADRs live
  doc_globs: []                     # extra docs to ingest as DocChunks
  commit_messages: off              # ingest recent conventional/issue-ref commits
  infer_governs: off                # optional budgeted LLM pass for unlinked decisions
```

## Linking: parsed first, LLM optional

`GOVERNS` edges are created from **unambiguous mentions** in the ADR prose (a
symbol named once, resolved uniquely). For decisions with no parsed link, an
**opt-in budgeted LLM pass** (`infer_governs`, `ckg enrich --decisions`) proposes
edges with confidence + rationale — it never overrides parsed links and is off by
default.
