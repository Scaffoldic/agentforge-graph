# ADR-0009: Top-10 language scope for 0.1 with A/B support tiers

## Metadata

| Field | Value |
|---|---|
| **Number** | 0009 |
| **Title** | Top-10 indexed-language scope for 0.1, split into A/B support tiers |
| **Status** | Accepted |
| **Date** | 2026-06-11 |
| **Deciders** | kjoshi |
| **Tags** | scope, ingestion, language-support |

---

## 1. Context and problem statement

How many languages should agentforge-graph index at 0.1, and at what
quality? Tree-sitter (ADR-0002) makes adding a language cheap to
*start* — a query pack, not a compiler — but resolution quality varies
sharply: Go, Java, C#, Python have clean import systems that resolve
well syntactically, while C++ (preprocessor, templates, overloads)
cannot be resolved from syntax alone. Indexing only 2 languages
under-serves real polyglot repos; promising precise resolution for all
10 would over-promise on the hard ones. What is the 0.1 scope, and how
do we set honest expectations per language?

## 2. Decision drivers

- Real repos are polyglot; a credible CKG must cover the mainstream
  stack, not just Python.
- Provenance discipline (ADR-0004) forbids emitting confident
  `resolved` edges we cannot actually justify.
- tree-sitter keeps the *marginal* cost of a language low, but each
  pack still needs descriptor rules, resolution semantics, and golden
  fixtures.
- Each pack should be shippable independently so breadth parallelizes
  instead of serializing one giant feature.

## 3. Considered options

1. **2 languages (Python + TS)** — minimal, fast to MVP.
2. **Top 10, uniform "full support" promise** — Python, TS, JS, Java,
   Go, C#, Rust, Ruby, PHP, C++ all claimed fully resolved.
3. **Top 10, two support tiers** — Tier A resolves; Tier B is
   structural + heuristic refs with opt-in LSP-assist.

## 4. Decision outcome

**Chosen: Option 3 — top 10 with A/B tiers.** 0.1 indexes Python,
TypeScript, JavaScript, Java, Go, C#, Rust, Ruby, PHP, C++.
**Tier A** (Python, TS, JS, Java, Go, C#, Rust, Ruby, PHP) gets full
pass-1 extraction plus confident pass-2 `CALLS`/`IMPORTS` resolution.
**Tier B** (C++) gets nodes, `CONTAINS`, and `#include`/`IMPORTS`
edges, with call resolution best-effort — refs stay `parsed` and only
become `resolved` via opt-in LSP-assist. Each language pack is an
independently mergeable unit under feat-002 sharing the `Extractor`
conformance suite, so packs land on separate PRs. v0.2 candidates:
Kotlin, Swift, C, Scala.

### Positive consequences

- Covers the mainstream polyglot stack at launch.
- Honest per-language expectations — no fake confidence on C++.
- Packs parallelize across contributors; a weak pack degrades visibly,
  it doesn't block the rest.

### Negative consequences (trade-offs)

- 10 packs is materially more 0.1 work than 2; the critical path to
  MVP widens (flagged in the tracker as the biggest time-to-MVP
  lever — a Tier-A subset could ship first with the rest as 0.1.x).
- Tier B users get less from C++ until LSP-assist or a future
  compiler-assisted path matures.

## 5. Pros and cons of the options

### Option A: 2 languages
- + Fastest to MVP; smallest surface.
- − Under-serves polyglot repos; re-opens scope immediately.

### Option B: Top 10, uniform promise
- + Simple story.
- − Over-promises C++ resolution; violates provenance honesty when
  syntax can't deliver.

### Option C: Top 10, A/B tiers
- + Broad *and* honest; parallelizable; clean degradation.
- − More 0.1 work; per-tier nuance to document.

## 6. References

- feat-002 (language packs, A/B tiers, support table), feat-005
  (chunker inherits the set), feat-011 (frameworks unblocked by the
  language set), TRACKER (v0.1 scope, parallelism note).
- Related: ADR-0002 (tree-sitter), ADR-0004 (provenance honesty).
