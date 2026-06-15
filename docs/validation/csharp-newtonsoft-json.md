# JamesNK/Newtonsoft.Json (C#) — validation run

W3 run, C# (8th pack) — a second **namespace** model, distinct from PHP/Java:
`using App.Geo` imports a whole *namespace*, not a class. A real, ubiquitous JSON
library.

- **repo:** https://github.com/JamesNK/Newtonsoft.Json @ `13.0.3`
- **date:** 2026-06-15
- **pipeline:** index ✅ · embed ⬜ · enrich ⬜ (structural validation)
- **command:** `ckg index /tmp/njson --include 'Src/Newtonsoft.Json/**' --exclude '**/obj/**'`

## Counts

```
indexed 233 files: 3206 nodes, 10321 edges
  nodes: Class=303, Interface=19, Method=2534, Function=117, File=233
  edges: CALLS=392, CONTAINS=2973, IMPORTS=6956
  imports: 6175 in-repo + 781 external
  calls:   392 resolved / 8740 unresolved
```

## Scores

| Dimension | Result | Verdict |
|---|---|---|
| **Parse coverage** | 233/233 files parsed, 0 skipped | ✅ excellent |
| **Symbol extraction** | 303 classes (`JsonConvert`/`JObject`/`JToken`/`JsonReader`→Class), 19 interfaces (`IJEnumerable`→Interface), 2534 methods, struct/enum/record→Class | ✅ strong |
| **Import resolution (namespace-prefix)** | **6175 in-repo** — `using Newtonsoft.Json.X` resolves to every in-repo file declaring that namespace (and binds its symbols); 781 external (`System.*`) | ✅ works (dense — see note) |
| **Call resolution** | 392 resolved — higher than pure-OO Java/PHP because binding a used namespace's symbols lets some unqualified calls resolve; the rest are member dispatch (ADR-0004) | ✅ partial |
| **Routes / decisions** | none (a library) — correctly empty | ✅ n/a |
| **Retrieval / enrichment / MCP** | not run this pass | ⬜ pending |

## What this run validated

- **A second namespace import model** — C# `using NS` names a *namespace*, so the
  resolver maps it to **every in-repo file declaring that namespace** and binds
  all their symbols (vs PHP/Java where a `use`/`import` is a single class FQN).
  This shares the namespace index but uses a prefix (wildcard) lookup, gated by a
  `namespace_import_prefix` pack flag.
- **Symbol extraction is comprehensive** — classes, structs, enums, records,
  interfaces, methods, constructors.
- **Note — namespace fan-out**: because one `using` links to *all* files in the
  namespace, in-repo IMPORTS are dense (~26/file here). That's a faithful
  representation of namespace-level coupling, but it inflates the import graph;
  representing an in-repo namespace as a single intermediate node (to collapse the
  fan-out) is a sensible follow-up.

## Findings

- No correctness bug. Follow-ups (not blockers):
  - **Namespace-node representation** to collapse the `using`→N-files fan-out
    (keeps impact analysis crisp on large C# repos).
  - `using static` / `using X = …` (alias) forms — only plain `using NS;` is
    resolved; aliases/static are a query extension.
  - Member-call resolution = the shared ADR-0004 boundary.

## Creds-enabled run (2026-06-15, live AWS Bedrock)

embed 2594 chunks (Cohere embed-v4) + enrich (Claude Haiku), **~$0.33** (the
priciest — largest repo). One transient Bedrock connection reset mid-embed; a
re-run completed cleanly.

- **Retrieval — good** (~2/3): "how is a json string deserialized" →
  `JsonConvert.DeserializeObject` (exact); "how is a json token read" →
  `JTokenReader.SetToken` (exact-ish); "how is an object serialized to json" →
  `JsonConvert` (adjacent — landed near `SerializeObject`).
- **Summaries** accurate (repo summary frames it around JsonReader/JsonWriter +
  the `JToken` hierarchy with LINQ). ✅
- **Pattern tags — 28** (63 candidates): **Factory 19, Strategy 5, Builder 2,
  Adapter 2** — Json.NET is factory-heavy; precise and well-recalled.

## Next

1. ✅ **C# pack shipped + validated on Newtonsoft.Json** (this run).
2. Continue W3: Rust (Tier A) + C++ (Tier B) — then W3 is complete.
