# CKG query grammar (read-only Cypher subset)

**Language version: 1.0** (`QUERY_LANG_VERSION` in `schema.py`; reported by
`ckg status`). This file is the **source of truth** for what the parser accepts.
Adding a clause is a *minor* bump; changing the meaning of an existing clause is
a *major* bump. Keep the parser productions and this EBNF in lock-step.

The surface is a deliberately small, **read-only** subset of openCypher. Caller
text is never executed — it is parsed into the `QueryAst` (the trust boundary),
validated, then compiled per backend. Anything not in this grammar does not
parse; a few shapes the grammar *can* express are rejected by the validator (see
"Validator-enforced rules").

## EBNF

```ebnf
query        = "MATCH" pattern { "," pattern }
               [ "WHERE" expr ]
               "RETURN" [ "DISTINCT" ] returnItem { "," returnItem }
               [ "ORDER" "BY" orderKey { "," orderKey } ]
               [ "SKIP" INT ]
               [ "LIMIT" INT ] ;

pattern      = nodePat { relPat nodePat } ;
nodePat      = "(" [ IDENT ] [ ":" IDENT ] [ props ] ")" ;
props        = "{" propEq { "," propEq } "}" ;
propEq       = IDENT ":" literal ;

relPat       = ( "-" | "<-" ) [ "[" [ IDENT ] [ ":" IDENT ] [ varlen ] "]" ] ( "-" | "->" ) ;
varlen       = "*" [ INT ] [ ".." [ INT ] ] ;   (* bounds; unbounded rejected at validation *)

expr         = orExpr ;
orExpr       = andExpr { "OR" andExpr } ;
andExpr      = notExpr { "AND" notExpr } ;
notExpr      = "NOT" notExpr | primary ;
primary      = "(" expr ")" | patternExists | predicate ;
patternExists= pattern ;                          (* a path with >= 1 relationship *)
predicate    = propRef ( compareOp literal
                       | "IN" "[" literal { "," literal } "]"
                       | stringOp STRING ) ;
compareOp    = "=" | "<>" | "<" | "<=" | ">" | ">=" ;
stringOp     = "STARTS" "WITH" | "ENDS" "WITH" | "CONTAINS" ;

returnItem   = ( aggregate | propRef | IDENT ) [ "AS" IDENT ] ;
aggregate    = ( "count" | "collect" | "min" | "max" | "avg" )
               "(" [ "DISTINCT" ] ( propRef | IDENT | "*" ) ")" ;   (* "*" only for count *)
orderKey     = ( propRef | IDENT ) [ "ASC" | "DESC" ] ;

propRef      = IDENT "." IDENT { "." IDENT } ;    (* f.name, n.attrs.role *)
literal      = STRING | [ "-" ] ( INT | FLOAT ) | "true" | "false" | "null" ;

IDENT        = /[A-Za-z_][A-Za-z0-9_]*/ ;
STRING       = /'...'/ | /"..."/ ;                (* backslash escapes: \n \t \r \\ \' \" *)
INT          = /[0-9]+/ ;
FLOAT        = /[0-9]+\.[0-9]+/ ;
```

Keywords are case-insensitive. Aggregate function names are not reserved.

## Excluded by construction (no production — a `ParseError`)

Writes/DDL (`CREATE`, `MERGE`, `SET`, `DELETE`, `DETACH`, `REMOVE`, `DROP`),
procedure/function `CALL`, and the `WITH` / `UNWIND` / `FOREACH` / `LOAD CSV` /
`USE` clauses. There is simply no rule that accepts them, so the read-only
guarantee starts at the grammar.

## Validator-enforced rules (parses, but rejected)

- Node labels must be a `NodeKind`; relationship types must be an `EdgeKind`
  (feat-001 locked vocabulary).
- Property references must be a curated name (`name`, `kind`, `path`,
  `start_line`, `end_line`, `source`, `extractor`, `commit`, `confidence`) or an
  opaque `attrs.<key>`. Every referenced variable must be bound in `MATCH`.
- **Unbounded variable-length** paths (`[*]`, `[*2..]`) are rejected — give an
  upper bound (`[:CALLS*1..3]`).
- Multiple `MATCH` patterns must be connected by shared variables; disconnected
  patterns (a Cartesian product) are rejected. A comparison's right-hand side is
  a **literal** — property-to-property comparison is not in the v1 subset, so a
  `WHERE` cannot be used to join otherwise-disconnected patterns.

## Capability tiers

Each construct maps to a capability a backend declares: `core`, `agg.basic`,
`pattern.exists`, `string.pred`, `path.varlen` (the mandatory **core tier**), and
optional extensions such as `agg.collect`. A construct the target backend does
not declare raises a `CapabilityError` naming what is supported — it is never
silently degraded.
