# W4 — agent dogfood over the CKG tools

The W4 bar: **a real agent answers real questions, unattended, using the CKG
tools.** Run on this repo (agentforge-graph itself — the canonical dogfood
target: Python, 9 ADRs, the differentiators present).

- **date:** 2026-06-15
- **model:** `anthropic:claude-sonnet-4-6` (framework `Agent`, live Anthropic API)
- **graph:** `ckg index . --embed` → 210 files, 1478 nodes (177 Class, 698
  Function, 393 Method, **9 Decision**), 1355 chunks (Cohere embed-v4)
- **tools:** `code_graph_tools(".")` — the **same nine `Tool` instances** the MCP
  server (`serve-mcp`, stdio/http) exposes (one definition, both call sites;
  `serve/server.py`). So this exercises the exact agent-facing tool surface.

## Questions → the agent tool-chose, chained, and answered correctly

| # | Question | Tools the agent chose (autonomously) | Verdict |
|---|---|---|---|
| 1 | "What languages does this CKG support? Find the language packs." | `ckg_repo_map` → `ckg_search` → `ckg_symbol` (9 steps) | ✅ listed all **10** packs from `BUILTIN_PACKS` (`packs/__init__.py`) |
| 2 | "What ADRs are recorded and what do they govern?" | `ckg_decisions` (4 steps) | ✅ all **9 ADRs**, status/date + governed symbols (e.g. ADR-0001 governs `KnowledgeIngestor#ingest`) |
| 3 | "Who depends on `reranker_from_config`?" | `ckg_search` → `ckg_impact` (7 steps) | ✅ the **2 callers**: `CodeGraph.retrieve` (production) + the rerank test |

**Total ≈ \$0.24** for the three (Sonnet 4.6).

## What this proves

- **Unattended tool-use + chaining works.** The agent picked the right tool for
  each question and *chained* on its own — search → take a `symbol_id` → impact;
  repo_map → search → symbol. No human in the loop.
- **Answers are grounded and correct** — each is verifiable against the graph
  (10 packs, 9 ADRs, the exact two callers). No hallucinated symbols.
- **The differentiators reach the agent** — `ckg_decisions` surfaced the ADRs and
  what they govern, which is the whole point of the decision graph.
- Because `code_graph_tools` and `serve-mcp` bind the **same** `Tool` objects, this
  validates the MCP tool surface itself; the MCP **transports** (stdio + the
  authed HTTP, ENH-005) are separately covered by the feat-008 / ENH-005 tests.

## Notes / follow-ups

- This drives the tools **in-process** (the AgentForge `Tool` path), the documented
  embedded consumption mode. A literal MCP-client→`serve-mcp`-server agent loop
  would add nothing to *tool* coverage (identical instances) but would exercise the
  wire protocol end-to-end — a nice-to-have if a hosted deployment needs it.
- Cost/latency scale with the agent's step count; read-only tools keep each step
  cheap.

## Cross-language dogfood — a NON-Python repo (Go / spf13 cobra)

Pre-0.1 validation item 5: confirm the tools serve agents across languages, not
just on this (Python) repo. Same harness, a Go codebase.

- **date:** 2026-06-16
- **model:** `anthropic:claude-sonnet-4-6` (framework `Agent`, live Anthropic API)
- **repo / graph:** `spf13/cobra` — `ckg index --lang go --embed` → 36 files, 727
  nodes (14 Class/struct, 168 Method, 427 Function, 1 Interface), 1592 CALLS
  resolved (Go same-package resolution), 1078 chunks (Cohere embed-v4).
- **tools:** `code_graph_tools("/tmp/ckg-cobra")` — the same nine `Tool` instances.

| # | Question | Tools the agent chose (autonomously) | Verdict |
|---|---|---|---|
| 1 | "Core types of this Go CLI library and where commands get executed?" | `ckg_repo_map` → `ckg_search` → `ckg_symbol` (16 steps) | ✅ identified `Command` (`command.go:54`), `Group`, `PositionalArgs`, `CompletionFunc` with exact file:line, and the `Execute`/`ExecuteC`/`execute` path |
| 2 | "Find `Execute` and report its callers." | `ckg_search` → `ckg_impact` (4 steps) | ✅ `(*Command).ExecuteContext` (public) + the test callers; even flagged a likely spurious template edge as such |
| 3 | "List the methods on the `Command` type." | `ckg_search` → `ckg_neighbors` → `ckg_repo_map` (6 steps) | ✅ a comprehensive, grounded list of real `*Command` methods (`Execute`, `ExecuteContext`, `SetArgs`, `SetContext`, lifecycle setters, …) |

**Total ≈ \$0.55** for the three (Sonnet 4.6). The agent chose and chained tools
unattended on a Go graph, answers grounded against real cobra symbols/spans — no
hallucinated symbols. Confirms cross-language agent tool-use (Go in addition to the
Python run above; the other 9 packs are retrieval-validated in the sibling
`docs/validation/*` files).

## Verdict

**W4 met** (Python + Go). A real agent answers real questions over the CKG tool
surface, unattended, choosing and chaining tools correctly — including the
decision/impact differentiators — and does so **across languages**, not just on the
Python home repo.
