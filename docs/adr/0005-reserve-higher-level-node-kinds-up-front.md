# ADR-0005: Reserve higher-level node/edge kinds in the schema up front

## Metadata

| Field | Value |
|---|---|
| **Number** | 0005 |
| **Title** | Reserve higher-level node/edge kinds in the schema at 0.1 |
| **Status** | Accepted |
| **Date** | 2026-06-11 |
| **Deciders** | kjoshi |
| **Tags** | architecture, schema, versioning |

---

## 1. Context and problem statement

The differentiator features land late — ADR/docs ingestion (feat-010)
at 0.3, framework extractors (feat-011) and LLM enrichment (feat-012)
at 0.4 — but they introduce new node kinds (`Decision`, `Route`,
`DataModel`, `Service`, `Summary`) and edge kinds (`GOVERNS`,
`HANDLED_BY`, `SUMMARIZES`…). If the schema and storage adapters only
learn about these kinds when their producers ship, then every adapter,
every query path, and every persisted index must migrate at 0.3 and
again at 0.4. How do we evolve toward the differentiators without
forcing schema migrations on persisted graphs at every minor release?

## 2. Decision drivers

- 0.x should avoid data migrations; the index is derivable, but
  re-deriving a large repo is not free, and adapter rewrites are
  risky.
- Storage adapters (feat-003) and retrieval (feat-006) should handle
  the full kind vocabulary from day one so later producers are
  pure additions.
- Reserving names is cheap; reserving *behavior* prematurely is not —
  the attr shapes of late kinds aren't settled yet.

## 3. Considered options

1. **Add kinds when their feature ships** — extend the enum and
   migrate adapters/data each time.
2. **Reserve all kinds at 0.1** — lock the full node/edge kind
   vocabulary now; producers fill them in later.
3. **Open/untyped kinds** — store kind as a free string, no enum.

## 4. Decision outcome

**Chosen: Option 2 — reserve the full kind vocabulary at 0.1.** feat-001
locks every node and edge kind now, including the higher-level ones
whose producers ship at 0.3/0.4. They are *names with reserved
semantics* — their detailed attr shapes are specced in their owning
features and may change until those features ship. Adapters store and
preserve any kind from the start (with an ignore-and-preserve rule for
kinds they don't specifically optimize), so a newer producer never
forces an older adapter or a persisted index to migrate.

### Positive consequences

- No schema migration at 0.3 or 0.4; producers are additive.
- Storage and query code is written once against the full vocabulary.
- Forward compatibility: an older adapter preserves newer kinds it
  doesn't understand.

### Negative consequences (trade-offs)

- Some reserved kinds may be refined before their producer ships;
  their attr contracts are explicitly unstable until then.
- The schema lists kinds with no producer for a while — a documentation
  burden (the feature catalogue maps each kind to its owning feature).

## 5. Pros and cons of the options

### Option A: Add kinds per feature
- + Schema only ever describes shipped behavior.
- − Migration churn at every differentiator release; adapter rewrites;
  the exact cost we want to avoid.

### Option B: Reserve all kinds at 0.1
- + Zero migration; additive producers; forward-compatible adapters.
- − Reserved-but-empty kinds; attr shapes provisional until producers
  land.

### Option C: Untyped string kinds
- + Infinitely extensible, never migrates.
- − No validation; typos become silent new kinds; loses the
  fail-at-startup guarantee and query safety.

## 6. References

- feat-001 (kind vocabulary, ignore-and-preserve), feat-003
  (adapters preserve unknown kinds), feat-010/011/012 (producers).
- Related: ADR-0004 (provenance), ADR-0006 (storage).
