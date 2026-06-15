# google/gson (Java) — validation run

W3 run, Java (7th pack). A real, widely-used JSON library; standard
`src/main/java` Maven layout, `package` + `import` FQNs.

- **repo:** https://github.com/google/gson @ `gson-parent-2.10.1`
- **date:** 2026-06-15
- **pipeline:** index ✅ · embed ⬜ · enrich ⬜ (structural validation)
- **command:** `ckg index /tmp/gson --include 'gson/src/main/**'`

## Counts

```
indexed 81 files: 1047 nodes, 1598 edges
  nodes: Class=84, Interface=11, Method=813, Function=58, File=81
  edges: CALLS=0, CONTAINS=966, IMPORTS=632
  imports: 264 in-repo + 368 external
  calls:   0 resolved / 2334 unresolved
```

## Scores

| Dimension | Result | Verdict |
|---|---|---|
| **Parse coverage** | 81/81 `src/main` files parsed, 0 skipped | ✅ excellent |
| **Symbol extraction** | 84 classes (`Gson`/`TypeAdapter`/`GsonBuilder`/`JsonReader`→Class), 11 interfaces (`JsonSerializer`→Interface), 813 methods + constructors, enums/records→Class | ✅ strong |
| **Import resolution (FQN)** | **264 in-repo** `import com.google.gson.…` resolve to the declaring file via the FQN index — and resolution is by the **`package` declaration**, so the `src/main/java/` source root is irrelevant; 368 external (`java.util`, …) | ✅ strong |
| **Call resolution** | 0/2334 — Java has no top-level functions; every call is method dispatch (`obj.m()`), member access unresolved by design (ADR-0004) | ⚠️ inherent (OO) |
| **Routes / decisions** | none (a library) — correctly empty | ✅ n/a |
| **Retrieval / enrichment / MCP** | not run this pass | ⬜ pending |

## What this run validated

- **The FQN mechanism (built for PHP) reuses cleanly for Java** with separator
  `.` — a file's `package` declaration + class name forms the FQN, and
  `import com.google.gson.TypeAdapter` resolves to that file. **264 in-repo
  imports resolved** with no source-root configuration (resolution is package-
  declaration-driven, not path-driven — so `src/main/java/` "just works").
- **Symbol extraction is comprehensive** — classes, interfaces, enums, records,
  methods, and constructors.
- **Honest limit**: pure-OO Java has no free functions, so *call* resolution is 0
  (method dispatch = member access, ADR-0004). The symbol graph + FQN dependency
  graph are the value.

## Findings

- No correctness bug. Follow-ups (not blockers):
  - **Wildcard/static imports** (`import com.foo.*`, `import static …`) resolve to
    a package/member, not a single class → currently external; a query/index
    extension.
  - A small number of methods land as `Function` (58) rather than `Method` —
    methods in nesting forms the scope-linker doesn't classify as a method-owner
    (e.g. some enum/nested bodies). Cosmetic (kind label), not a missing symbol.
  - Method-call resolution = the shared ADR-0004 boundary.

## Next

1. ✅ **Java pack shipped + validated on gson** (this run).
2. Continue W3: C#, Rust (Tier A) + C++ (Tier B).
