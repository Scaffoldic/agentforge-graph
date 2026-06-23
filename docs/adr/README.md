# Architecture Decision Records

Load-bearing architectural decisions for **agentforge-graph** are
captured here as immutable ADRs in the **MADR (Markdown ADR) format**
(Nygard's template extended with decision drivers and option-by-option
pros/cons; compatible with arc42 §9).

> **Why ADRs.** These records preserve the *why* behind each choice so
> a future contributor can challenge it from the original context,
> drivers, and alternatives — and either confirm it still holds or
> write a superseding ADR. They are derived from the prior-art survey
> behind the design and realized in the specs under
> [`../features/`](../features/).

## Format

4-digit zero-padded ids (`0001`, …) that sort lexicographically.
Numbers are **immutable**. A record that no longer reflects practice is
marked **Superseded by ADR-NNNN** and stays in place; the superseding
ADR references it. Template:
[`/.claude/templates/adr.md`](../../../../.claude/templates/adr.md).

## Status legend

| Status | Meaning |
|---|---|
| **Proposed** | Drafted, awaiting acceptance |
| **Accepted** | Active — describes current architecture |
| **Superseded by ADR-NNNN** | Replaced; kept for history |
| **Deprecated** | No longer relevant; not yet superseded |

## Index

| # | Title | Status | Tags | Realized in |
|---|---|---|---|---|
| [0001](0001-build-on-agentforge-framework.md) | Build on the AgentForge framework | Accepted | architecture, platform | all features |
| [0002](0002-tree-sitter-over-compiler-grade-extraction.md) | Tree-sitter (no-build) over compiler-grade extraction | Accepted | parsing, ingestion | feat-002 |
| [0003](0003-stable-symbol-ids-and-per-file-subgraphs.md) | Stable descriptor-based symbol IDs + per-file subgraphs | Accepted | identity, incrementality | feat-001, 002, 004 |
| [0004](0004-provenance-on-every-fact.md) | Provenance on every node and edge | Accepted | schema, trust | feat-001, 006, 010, 012 |
| [0005](0005-reserve-higher-level-node-kinds-up-front.md) | Reserve higher-level node/edge kinds at 0.1 | Accepted | schema, versioning | feat-001 |
| [0006](0006-embedded-first-pluggable-storage.md) | Embedded-first, pluggable graph + vector storage | Accepted | storage, packaging | feat-003 |
| [0007](0007-ast-aware-chunking-with-chunk-symbol-separation.md) | AST-aware chunking with chunk↔symbol separation | Accepted | retrieval, chunking | feat-005 |
| [0008](0008-hybrid-retrieval-vector-then-graph.md) | Hybrid retrieval (vector → graph), deterministic path | Accepted | retrieval | feat-006 |
| [0009](0009-top-10-language-scope-with-support-tiers.md) | Top-10 language scope for 0.1 with A/B tiers | Accepted | scope, language-support | feat-002 |

## Process

- **New ADR:** copy the template, take the next number, fill every
  section, set `Proposed`, open a PR.
- **Reviewing:** focus on context and drivers; the chosen option is
  fine if alternatives are honestly considered.
- **Superseding:** write a new ADR explaining what changed; edit the
  old one's status line to `Superseded by ADR-NNNN` — do not delete or
  otherwise edit its body.

## References

- Michael Nygard — *Documenting Architecture Decisions* (2011).
- MADR v3: https://adr.github.io/madr/ · arc42 §9:
  https://docs.arc42.org/section-9/
