# ADR-0004: Provenance on every node and edge

## Metadata

| Field | Value |
|---|---|
| **Number** | 0004 |
| **Title** | Provenance (source + confidence) on every node and edge |
| **Status** | Accepted |
| **Date** | 2026-06-11 |
| **Deciders** | kjoshi |
| **Tags** | architecture, schema, trust |

---

## 1. Context and problem statement

agentforge-graph mixes facts of very different reliability in one
graph: syntactically-parsed structure (high confidence), import-graph-
resolved call edges (good but heuristic), framework-pattern matches
(curated rules), and LLM-generated knowledge — summaries, design-
pattern tags, inferred ADR-governance links (plausible but
fallible). If an agent cannot tell a parsed fact from an LLM guess, the
guess masquerades as ground truth and the graph becomes untrustworthy
the moment we start enriching it. How do we let the differentiator
features write inferred knowledge into the graph without poisoning the
deterministic core?

## 2. Decision drivers

- LLM enrichment (feat-010, feat-012) is a headline differentiator —
  it *must* be allowed, but must never be confused with parsed fact.
- Retrieval (feat-006) needs to rank and filter by reliability
  ("resolved beats parsed", "exclude LLM facts").
- Debuggability: when a wrong edge surfaces, we need to know which
  extractor produced it and at which commit.
- The cost (a small struct per fact) must be justified by query-time
  value.

## 3. Considered options

1. **No provenance** — all facts equal; track origin out-of-band if at
   all.
2. **Per-batch provenance** — tag whole ingestion runs, not individual
   facts.
3. **Per-fact provenance** — every `Node`/`Edge` carries
   `source ∈ {parsed, resolved, llm, manual}`, `extractor`, `commit`,
   `confidence`.

## 4. Decision outcome

**Chosen: Option 3 — per-fact provenance.** Every node and edge carries
a `Provenance` value (source, extractor name+version, git commit,
confidence; `confidence < 1.0` only meaningful for `source="llm"`).
This is enforced at the `Node`/`Edge` constructor in feat-001, so no
producer can emit an unattributed fact. Retrieval exposes
`min_provenance` and `include_llm_facts` filters; rankers weight
`resolved` above `parsed`; LLM-derived items render with an `[llm]`
marker.

### Positive consequences

- LLM enrichment is safe: inferred facts are visibly second-class,
  filterable, and confidence-thresholded.
- Retrieval quality improves (precise edges outrank heuristic ones).
- Every wrong fact is traceable to an extractor + commit.

### Negative consequences (trade-offs)

- Storage overhead per fact (small; bounded struct).
- Producers must supply provenance — minor boilerplate, offset by
  helper constructors (`Provenance.parsed(...)`, `.llm(...)`).

## 5. Pros and cons of the options

### Option A: No provenance
- + Simplest schema.
- − Cannot rank by reliability; LLM facts indistinguishable from
  parsed; the moment enrichment lands, trust collapses.

### Option B: Per-batch provenance
- + Cheaper than per-fact; some traceability.
- − Cannot filter a single inferred edge inside a mostly-parsed file;
  too coarse for retrieval ranking.

### Option C: Per-fact provenance
- + Exact filtering and ranking; full traceability; safe enrichment.
- − Per-fact overhead and producer boilerplate.

## 6. References

- feat-001 (`Provenance` type, constructor enforcement), feat-006
  (filters/ranking), feat-010 & feat-012 (LLM provenance enforced).
- Related: ADR-0005 (reserved kinds), ADR-0008 (retrieval ranking).
