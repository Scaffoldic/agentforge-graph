# feat-016: Grounded documentation generation (`ckg docs …`)

## Metadata

| Field | Value |
|---|---|
| **ID** | feat-016 |
| **Title** | Grounded documentation generation — docs as a cited projection of the graph |
| **Status** | accepted |
| **Target version** | 0.7.0 |
| **Layer** | 3 differentiator (framework layer) — turns the graph *outward* into the standard dev docs |
| **Area** | new `agentforge_graph.docgen` (framework layer; imports `agentforge` for LLM calls) · CLI (`ckg docs …`) |
| **Depends on** | feat-006 (retrieval), feat-007 (repo map), feat-010 (doc/ADR ingestion + GOVERNS/DESCRIBES), feat-012 (LLM enrichment + budget rails), feat-004 (DirtySet staleness) |
| **Graduated from** | [FA-006](../feature-analysis/FA-006-grounded-documentation-generation.md) |
| **Relates to** | feat-013 (FA-002 — the AI-context file this generates is what `ckg setup` wires up), feat-014 (FA-005 — CI regeneration), KL-001 (LLM hallucination) |

---

## 1. Why this feature

The CKG already contains the raw material that documentation *is* — typed
structure, framework semantics (routes/ORM/DI), module/repo summaries,
design-pattern tags, existing ADRs/docstrings, centrality, and history. Yet
teams still hand-write (and let rot) the standard development docs: the
AI-assistant context file, the architecture overview, per-component docs, and
design documents.

This feature generates those docs as a **grounded projection of the graph.**
Not "an LLM writes a README from scratch" — instead, assemble a *cited* context
pack from graph facts and have the model **compose prose over facts it can
attribute to real symbols/edges**, with provenance. The result is documentation
that is **verifiable, regenerable, and linked back to the code it describes** —
and, opt-in, can be **fed back into the graph** to make the codebase
progressively more self-documenting.

This is the natural capstone on enrichment (feat-012) and doc ingestion
(feat-010): we already summarize and ingest docs; this turns the graph outward
into the artifacts developers and their agents need to reason well.

## 2. Why it ships in the engine

- **Grounding is only possible from inside the engine.** The value over a
  generic doc-bot is that every claim cites a real graph fact with provenance
  (ADR-0004). That requires the graph + retrieval + repo map, which only the
  engine has.
- **The flywheel closes a loop the engine already half-owns.** feat-010 ingests
  + embeds + links docs; this produces the docs that feed it. Keeping both
  in-engine makes the round-trip coherent (and lets us prevent the echo chamber
  — §8).
- **Staleness must reuse one mechanism.** Generated docs go stale exactly like
  embeddings/summaries do; they ride the same feat-004 `DirtySet`, not a
  parallel staleness story.
- **Layering (ADR-0001):** `docgen` is the **framework layer** — it composes
  LLM calls over the deterministic engine's retrieve/repomap/store plus the
  feat-012 budget rails. The deterministic engine stays framework-free; only
  `docgen` imports `agentforge`.

## 3. How consumers benefit

- **Developer:** `ckg docs generate` produces an architecture overview,
  per-component docs, and design docs grounded in the real code — and keeps them
  fresh (`ckg docs update` regenerates only what changed).
- **AI assistant:** the generated CLAUDE.md/AGENTS.md orients the agent to the
  codebase automatically (and feat-013 `ckg setup` wires it in). Better context
  → better designs from the agent.
- **The graph itself:** once a developer opts to sync accepted docs back in
  (§10), retrieval and future generations get richer, compounding context.

## 4. Feature specifications

### 4.1 User-facing experience

```bash
# Generate — writes DRAFTS to a marked location; never overwrites human docs
ckg docs generate --type ai-context                 # CLAUDE.md / AGENTS.md draft
ckg docs generate --type architecture               # system overview
ckg docs generate --type component --scope src/pkg  # per-module doc(s)
ckg docs generate --type design --scope <subsystem> # "how it works + why"
ckg docs generate --all                             # every configured type

# Keep fresh — regenerate only docs whose underlying code changed (feat-004 DirtySet)
ckg docs update

# Review workflow
ckg docs list            # generated docs + their synced-commit + staleness
ckg docs diff <doc>      # what changed vs the last generated version
ckg docs promote <doc>   # mark a reviewed draft as accepted (human gate)

# Opt-in flywheel — re-ingest+embed ACCEPTED generated docs into the graph
ckg docs sync            # explicit; honors docgen.round_trip (default off)
```

ADR drafts get a ratification-flavored flow, **deferred to Phase 3** (§11) —
out of scope for feat-016 / 0.7.0.

### 4.2 Public API / contract

```python
class DocTarget:        # what to document
    type: DocType       # ai_context | architecture | component | design
    scope: str | None   # repo | package/path | subsystem | symbol id

class DocArtifact:
    type: DocType
    path: str                    # under the generated-docs root
    synced_commit: str           # the indexed commit this was generated from
    citations: list[SymbolRef]   # every claim traces to graph facts
    provenance: str              # always "llm" / generated
    status: str                  # draft | accepted
    stale: bool                  # underlying symbols changed since synced_commit

class DocGenerator:
    async def generate(self, target: DocTarget) -> DocArtifact
    async def update(self) -> list[DocArtifact]   # regenerate dirty docs only
    async def sync(self) -> int                   # re-ingest+embed ACCEPTED docs (opt-in)
```

- **Generated docs are `source: llm` and `status: draft`** until a human
  promotes them — never silently authoritative.
- **Citations are mandatory:** a generated section that cannot cite a graph fact
  is flagged, not emitted as confident prose.
- **Write surface is CLI/API only.** Generation mutates the working tree, so it
  is *not* an auto-invoked, agent-facing MCP tool (preserves feat-008's
  read-only tool discipline). A future opt-in write tool is out of scope here.

### 4.3 Internal mechanics

Per doc target:

1. **Assemble a grounded context pack.** Run a doc-type-specific *recipe* over
   the graph: `architecture` pulls layers + top-PageRank nodes + framework
   topology (routes/models/services) + repo summary; `component` pulls a
   module's CONTAINS/IMPORTS/public-API + its routes/models + summary; `design`
   pulls a subsystem's call graph + pattern tags + relevant ADRs/docstrings.
   Retrieval (feat-006) fills semantic gaps. `ai-context` pulls the repo map +
   layer topology + entry points + conventions surfaced from existing docs.
2. **Ground preferentially on high-provenance facts.** Prefer parsed/resolved
   code facts over `llm`-sourced chunks (anti-echo-chamber, §8). Carry each
   fact's `SymbolRef` so the renderer can cite it.
3. **Render via a doc-type template.** A template defines the section skeleton;
   the LLM fills sections *from the cited pack only*, attributing claims.
   Templates keep output consistent and reviewable.
4. **Emit a draft artifact** to the generated-docs root with a "generated by
   CKG, synced @<commit>, do not edit by hand" header, inline citations (symbol
   links), `status: draft`, and a provenance stamp.
5. **Register staleness.** The doc's source symbols are recorded; when they
   change, feat-004 `DirtySet` marks the doc dirty → `ckg docs update`
   regenerates only those.
6. **(Opt-in) sync.** `ckg docs sync` feeds **accepted** docs through feat-010
   ingestion → embedded (feat-005) → DESCRIBES/GOVERNS edges, tagged as
   generated so they never masquerade as ground truth.

Budget + idempotency reuse feat-012 rails: per-run USD cap, resumable on trip,
clear-before-rewrite so regeneration produces no duplicate artifacts.

### 4.4 Module packaging

`agentforge_graph.docgen` — **framework layer** (imports `agentforge` for LLM
calls; ADR-0001). Built on the deterministic engine's retrieve/repomap/store
plus the enrich budget rails. `ckg docs …` console subcommands. Ships in the
base install; the LLM provider is provider-selected exactly as feat-012 already
is (fake/scripted for CI; live provider env-gated).

### 4.5 Configuration

```yaml
docgen:
  output_root: docs/_generated      # drafts land here; human docs untouched
  types: [ai-context, architecture, component, design]   # Phase-1 set (opt-in per type)
  ai_context_targets: [CLAUDE.md, AGENTS.md]
  component_granularity: package    # package (default) | file | hybrid
  hybrid_min_symbols: 20            # hybrid: drill into files above this size
  require_citations: true           # sections without a citable fact are flagged
  round_trip: off                   # opt-in flywheel; `ckg docs sync` honors this
  promote_required: true            # docs are drafts until `ckg docs promote`
  budget_usd: 5.0                   # per-run cap (feat-012 BudgetPolicy)
  regenerate_on_ci: false           # feat-014 CI can flip this on (commit the diff in a PR)
```

Read via the engine's framework-free config path (ADR-0001): `app.docgen.*` or a
standalone `ckg.yaml` `docgen:` block. (The **engine-side** blocks stay
`agentforge`-free; `docgen` itself is framework layer and may read config via
the framework, but reuses the same `_Block` discovery for consistency.)

## 5. Plug-and-play & upgrade story

- New doc types register as **recipe + template pairs** (data, not core
  rewrites) — the same extensibility stance as framework packs / providers.
- Generated docs carry their `synced_commit`, so an upgrade that changes a
  template re-generates cleanly and the diff is reviewable.
- `round_trip: off` by default means adopting the flywheel is a deliberate,
  reversible choice.

## 6. Cross-language parity

Generation is graph-driven, so it works for any indexed language. Output quality
tracks how richly that language is modeled (a language with framework packs gets
routes/models in its component docs; one without still gets structure +
summaries).

## 7. Test strategy

- **Grounding/citation test (load-bearing):** every emitted section maps to ≥1
  real `SymbolRef`; an invented claim with no backing fact is flagged, not
  published. Fixture repo with a known graph.
- **No-overwrite test:** generation only ever writes under `output_root`;
  human-authored docs are byte-unchanged.
- **Staleness test:** edit a module → its component doc is marked dirty →
  `ckg docs update` regenerates *that* doc and not others (feat-004 reuse).
- **Draft/promote gate test:** generated docs are `status: draft`; `sync`
  refuses to round-trip un-promoted docs; `promote` flips status.
- **Anti-echo-chamber test:** with round-trip on, a second generation still
  grounds on code facts and tags generated docs distinctly (a generated doc is
  never cited as ground truth for a code claim).
- **Determinism/CI:** scripted-LLM fakes (feat-012 pattern) render templates
  with no model calls/creds, so the suite is hermetic; a live, env-gated test
  exercises a real model end-to-end.
- **Budget test:** a capped run trips the breaker and resumes idempotently (no
  duplicate/partial docs).

## 8. Risks & open questions

| Risk / Question | Mitigation / Decision |
|---|---|
| **Hallucination** (KL-001 amplified) | Ground on cited facts; `require_citations`; everything `source: llm` + `draft`; review gate before authoritative |
| **Doc drift / staleness** | `synced_commit` stamp + feat-004 dirty-tracking + `stale` flag + `ckg docs update` |
| **Echo chamber / model collapse** (round-trip) | Ground preferentially on high-provenance code facts; tag generated docs distinctly; never cite generated prose as ground truth; round-trip is opt-in |
| **Overwriting human docs** | Drafts land only under `docgen.output_root`; promotion is explicit |
| **Cost** | feat-012 budget rails: per-run cap, resumable, idempotent; `update` touches only dirty docs |
| **"Generate everything" scope creep** | Phased (§11); feat-016 is the four descriptive types only; ADR drafts + flywheel-hardening are later phases |
| Open: per-component doc granularity | Default per-package; `--scope` allows finer; `component_granularity` knob. Validate on a real repo during implementation |
| Open: house template style | Seed templates from the repo's own doc shapes; confirm during implementation |

## 9. Out of scope

- **ADR draft generation + ratification** — Phase 3 (§11); its own surface.
- **The opt-in flywheel hardening + CI regeneration** — Phase 2 (§11). feat-016
  ships `ckg docs sync` as the opt-in mechanism with `round_trip: off` default,
  but the *proven anti-echo-chamber CI loop* is a later phase.
- An auto-invoked, agent-facing *write* MCP tool (generation stays CLI/API;
  feat-008 tools stay read-only).
- Translating/localizing docs; publishing to an external docs site.
- Generating *test* code or code fixes (this feature documents; it does not
  write product code).
- Fabricating ADR rationale (we reconstruct candidates for humans — never assert
  a decision the team didn't make).

## 10. Design notes — resolved decisions

**A. Round-trip is OPT-IN.** Generated docs do **not** auto-feed the graph.
`round_trip: off` by default; `ckg docs sync` re-ingests + embeds **accepted**
docs only, tagged as generated. The flywheel is powerful but the echo-chamber
risk is real — make enabling it a deliberate, reversible choice.

**B. feat-016 ships all four descriptive types:** **AI-context
(CLAUDE.md/AGENTS.md), architecture overview, component docs, AND design
documents.** Design docs carry slightly higher synthesis/hallucination risk, so
they lean hardest on `require_citations` and the review gate — but they're in
scope. ADR drafts remain Phase 3.

**C. Review gate + draft status.** Generated docs land as clearly-marked
**drafts** under `output_root`; a human promotes them (`ckg docs promote`), or
in CI they're committed via a **PR for review** (feat-014), never auto-published
in place. Nothing generated becomes authoritative without a human in the loop.
`promote_required: true` by default.

**D. Documentation is a projection of the graph** — cited and provenance-
stamped, kept fresh by the same dirty-tracking as embeddings, and (opt-in) fed
back to make the codebase self-documenting. This is the thesis; the design doc
(design-016) resolves the file layout, recipe/template seam, citation model, and
chunk plan.

## 11. Phasing

feat-016 delivers **Phase 1** in full for 0.7.0:

1. **Phase 1 — descriptive docs (feat-016 / 0.7.0):** AI-context, architecture
   overview, component docs, design docs. Grounding + citations + draft/review
   gate + dirty-aware `update` + opt-in `sync`. Delivers "auto-update my AI
   assistance" immediately.
2. **Phase 2 — the flywheel, hardened (later):** proven anti-echo-chamber
   grounding + CI regeneration (feat-014) that opens a docs PR on merge-to-main.
3. **Phase 3 — ADR drafts + ratification (later):** decision reconstruction →
   draft ADRs → human ratify → GOVERNS linkage (feat-010).

**Component-doc granularity is configurable, opt-in first.** Component docs only
generate if `component` is in `docgen.types`. *How* they generate is a config
knob (`component_granularity`: `package` default | `file` | `hybrid`), with a
per-run `--scope` override.

## Implementation status

_Not started. Design doc: `design-016-grounded-doc-generation.md` (next)._

## 12. References

- [FA-006](../feature-analysis/FA-006-grounded-documentation-generation.md) — source analysis.
- [feat-006](feat-006-hybrid-retrieval.md) — retrieval that fills semantic gaps in the context pack.
- [feat-007](feat-007-repo-map-summarization.md) — repo map / centrality feeding the architecture recipe.
- [feat-010](feat-010-adr-and-docs-ingestion.md) — doc ingestion + GOVERNS/DESCRIBES the flywheel reuses.
- [feat-012](feat-012-llm-enrichment.md) — LLM enrichment + budget rails this composes over.
- [feat-004](feat-004-incremental-indexing.md) — DirtySet staleness the docs ride.
- [feat-013](feat-013-agent-auto-configuration.md) — `ckg setup` that wires the generated AI-context file.
- [feat-014](feat-014-watch-and-ci-indexing.md) — CI regeneration path (Phase 2).
- ADR-0001 (framework-free engine core), ADR-0004 (provenance).
- design-016 (the *how*: file layout, recipe/template seam, citation model, chunk plan) — written next.
