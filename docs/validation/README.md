# Validation — the road to a production-grade 0.1

0.1 is **not** "MVP feature-complete" (that's done). 0.1 is **"production-grade":
the graph knowledge is correct and useful on real, diverse codebases, and a real
agent can consume it over MCP.** This directory tracks that campaign.

The MVP proved each feature works on fixtures. Validation proves the *whole
pipeline* produces trustworthy knowledge on **real open-source repos across every
language we claim to support**, finds the gaps, and drives them to closure before
we tag 0.1.

## How it works

1. **Run the full pipeline** on a target OSS repo:
   `ckg index → embed → enrich → map/query/impact/routes/decisions`, then drive it
   through an agent over MCP (`docs/guides/using-over-mcp.md`).
2. **Score the graph knowledge** against ground truth (below).
3. **File every gap** as a `docs/bugs/BUG-NNN`, `docs/enhancements/ENH-NNN`, or
   `docs/known-limitations/KL-NNN` — and link it from the run's findings.
4. **Log the run** as `docs/validation/<lang>-<repo>.md` and update the matrix here.

CI stays fixture-based and model-free; validation is a **manual, periodic
campaign** with live models, run locally.

## What "validate the graph knowledge" means

Per repo, measure — not vibes:

| Dimension | Signal | Target (0.1) |
|---|---|---|
| **Parse coverage** | % files parsed vs skipped/errored | ≥ 98% of supported files |
| **Symbol extraction** | spot-check classes/functions/methods captured | no systematic misses |
| **Reference resolution** | % `CALLS`/`IMPORTS` resolved vs `parsed`-only | high, language-appropriate; **never fake-`resolved`** (ADR-0004) |
| **Impact correctness** | reverse-deps for a known symbol vs manual trace | no false edges; few misses |
| **Retrieval quality** | `ckg_search` top-k contains the right code for N seeded questions | usable hit-rate |
| **Repo-map usefulness** | does the budget map surface the actually-central modules | yes, by inspection |
| **Routes / decisions** | framework routes + ADR governance match reality | precise |
| **Enrichment honesty** | pattern tags/summaries are right and carry `llm` provenance | no confident hallucinations (see KL-001) |
| **MCP consumption** | an agent answers real questions using the tools, unattended | yes, on ≥1 repo per tier |

## Target repos (v0.1 language scope, feat-002)

Pick small-but-real repos; keep them pinned to a commit for reproducibility.

| Tier | Language | Candidate repo(s) | Run | Findings |
|---|---|---|---|---|
| A | Python | **pallets/click @ 8.1.7** | ✅ [run](python-click.md) — **full creds run done** (embed+retrieval+enrich on live Bedrock, ~$0.13) | BUG-004 (fixed), ENH-006 (done), ENH-007 (done) |
| A | TypeScript | **colinhacks/zod @ v3.23.8** | ✅ [run](typescript-zod.md) — **creds run done** (2026-06-15, ~$0.09; ENH-008 verified: Interface/TypeAlias/Variable 0→57/241/21) | BUG-005 (fixed), ENH-008 (done) |
| A | JavaScript | **expressjs/express @ 4.19.2 (CommonJS) + chalk @ v5.3.0 (ESM)** | ✅ [run](javascript-express-chalk.md) — **creds run done** (2026-06-15, express `lib/`, ~$0.02) | BUG-006 (fixed); ESM works |
| A | Go | **spf13/cobra @ v1.8.0** | ✅ [run](go-cobra.md) — **pack shipped** (first directory-package lang): 19 files, 511 same-package CALLS, go.mod-aware imports | no bug; follow-ups: receiver→method link, struct fields |
| A | Java | **google/gson @ 2.10.1** | ✅ [run](java-gson.md) — **pack shipped** (FQN model reused, sep `.`): 81 files, 84 classes, 264 in-repo imports resolved | no bug; follow-up: wildcard/static imports |
| A | C# | **JamesNK/Newtonsoft.Json @ 13.0.3** | ✅ [run](csharp-newtonsoft-json.md) — **pack shipped** (namespace-prefix model): 233 files, 303 classes, 6175 in-repo namespace imports | no bug; follow-up: namespace-node to collapse fan-out |
| A | Rust | **serde-rs/json @ v1.0.108** | ✅ [run](rust-serde-json.md) — **pack shipped** (path-derived modules): 39 files, 197 classes, 608 resolved calls | no bug; follow-up: grouped/glob `use` |
| A | Ruby | **rails/thor @ v1.3.0** | ✅ [run](ruby-thor.md) — **pack shipped**: 36 files, 97 classes/modules, 394 methods, 42 require_relative imports | no bug; follow-up: load-path `require` |
| A | PHP | **Seldaek/monolog @ 3.6.0** | ✅ [run](php-monolog.md) — **pack shipped** (first namespace/FQN model): 119 files, 112 classes, 284 in-repo `use` imports resolved | no bug; follow-up: grouped/aliased `use` |
| B | C++ | **fmtlib/fmt @ 10.2.1** | ✅ [run](cpp-fmt.md) — **pack shipped** (Tier B): 16 files, 235 classes, 579 functions, 17 quoted includes resolved | no bug; follow-up: template kind-classification |
| — | **dogfood** | this repo (agentforge-graph, Python) | ⬜ | partially done (PR #15) |

> Note the gap between the **language packs that ship** (Python, TypeScript,
> **All 10 language packs now ship** (Python, TypeScript, JavaScript, Go, Ruby,
> PHP, Java, C#, C++, Rust) — the "10 languages" v0.1 claim is real. Each is
> validated on ≥1 real OSS repo above, **with a creds-enabled run** (live Bedrock:
> embed + retrieval + enrich).

### Creds-enabled retrieval/enrich — all 10 packs (2026-06-15)

Live AWS Bedrock (Cohere embed-v4 + Claude Haiku) across every shipped pack's
validation repo. **Total ≈ \$1.4** (the 7 new packs ≈ \$1.0; click/zod/express
earlier). Cross-language findings:

- **Embed + retrieval + enrich work on all 10** — no language-specific failures
  (one transient Bedrock connection reset on the largest repo, fixed by a re-run).
- **Retrieval precision tracks naming explicitness.** Sharpest where symbols are
  named directly: **Go (cobra 3/3 exact)** and **Rust (serde_json 3/3 exact)**;
  strong on Java/Ruby/C# (the canonical symbol is usually the exact hit);
  fair on dense/template C++ and prose-light code. Same pattern as zod/express:
  good-always, surgical where naming is explicit (ENH-009 is the precision lever).
- **Pattern tags scale with OO/GoF density, precisely.** gson **30** (Adapter 16/
  Factory 11), Newtonsoft.Json **28** (Factory 19/Strategy 5), serde **11**,
  monolog **7**, fmt **4**, cobra/thor **0** — the judge recalls real patterns
  where the codebase has them and declines cleanly where it doesn't (no false
  positives across hundreds of candidates).
- **Summaries** are accurate and architecture-grounded on every repo.

## Per-run template

Each `docs/validation/<lang>-<repo>.md`:

```markdown
# <repo> (<lang>) — validation run

- repo: <url> @ <commit>
- pipeline: index ✅ / embed ✅ / enrich ✅
- counts: <files> files, <symbols> symbols, <resolved>/<refs> refs resolved (%)

## Scores
<the dimensions table above, filled in>

## Findings
- BUG-NNN: ...
- ENH-NNN: ...
- KL-NNN: ...

## MCP dogfood
<questions asked through an agent + whether the tools answered them>
```

## Exit criterion for 0.1

- Every **shipped** language pack validated on ≥1 real repo with no open
  correctness (`BUG`) blocker.
- `ckg_search` / `ckg_impact` / `ckg_repo_map` demonstrably useful (seeded-question
  hit-rate + manual review) on those repos.
- A real agent answers real questions over MCP, unattended, on ≥1 repo per tier.
- Storage-backend decision resolved (ENH-004 — embedded-only vs server backends).
- Consumption + provider docs complete (`using-over-mcp.md`, `model-providers.md`).

When those hold, cut 0.1 (version bump, CHANGELOG, tag).
