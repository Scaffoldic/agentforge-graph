"""Capability tiers + the optional ``QueryCapable`` backend protocol (feat-015).

Every supported construct is tagged with a **capability**. A backend adapter
declares the set it can execute *identically* to the others. This replaces a
naive "intersection of all backends, forever" rule (which would cap a strong
backend at the weakest one) with a model that ships the same safe common core
today and grows additively: a construct outside a backend's declared set is
rejected *for that backend* with a precise error — never silently degraded, and
never removed from backends that do support it. The conformance suite guarantees
every construct is identical across the backends that claim it.

The ``CORE_TIER`` is mandatory: every query-capable backend must support it and
prove identical results in conformance. That is the 0.6.4 subset.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Protocol, runtime_checkable

from .ast import QueryAst

# --- capability names -------------------------------------------------------

CORE = "core"  # MATCH/WHERE/RETURN/ORDER/SKIP/LIMIT + comparisons + IN + booleans
AGG_BASIC = "agg.basic"  # count / min / max / avg
PATTERN_EXISTS = "pattern.exists"  # (a)-[:KIND]->(b) existence in WHERE
STRING_PRED = "string.pred"  # STARTS WITH / ENDS WITH / CONTAINS
PATH_VARLEN = "path.varlen"  # bounded variable-length rel, e.g. [:CALLS*1..3]

# Optional (a backend MAY advertise these; not part of the mandatory core):
AGG_COLLECT = "agg.collect"  # collect() list aggregation
ATTRS_ACCESS = "attrs.access"  # querying free-form n.attrs.<key> (needs a real
# map column, not a JSON string). No v1 backend advertises it: Kuzu/Neo4j store
# attrs as a JSON string, which native Cypher can't destructure portably without
# a workaround that breaks under aggregation — so attrs.* cleanly reports as
# unsupported via the capability seam until a backend can back it faithfully.

# Every query-capable backend MUST support these and prove identical results.
CORE_TIER: frozenset[str] = frozenset({CORE, AGG_BASIC, PATTERN_EXISTS, STRING_PRED, PATH_VARLEN})

# All capabilities the query language defines (core + optional).
ALL_CAPABILITIES: frozenset[str] = CORE_TIER | {AGG_COLLECT, ATTRS_ACCESS}


@dataclass(frozen=True)
class QuerySettings:
    """Execution bounds, resolved from ``QueryConfig`` (chunk 7)."""

    max_rows: int = 1000
    timeout_ms: int = 5000
    max_expansions: int = 50_000


@dataclass(frozen=True)
class ResultTable:
    """A normalized, backend-independent columnar result.

    ``columns`` is fixed by the query's RETURN order at compile time, so a row
    set is identical across backends. ``stopped_reason`` records *which* bound
    truncated the result (no silent caps, per feat-008)."""

    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    truncated: bool = False
    stopped_reason: str | None = None  # None | "row_cap" | "timeout" | "expansion_cap"


@runtime_checkable
class QueryCapable(Protocol):
    """A ``GraphStore`` adapter that can execute a validated ``QueryAst``.

    Optional — a backend without it reports ``query.enabled: false`` and still
    serves the typed verbs (the locked ``GraphStore`` ABC is untouched). An
    adapter opting in declares its ``query_dialect`` and ``capabilities`` and
    implements ``run_query`` (execution + guardrails land in chunk 2)."""

    query_dialect: ClassVar[str]  # "kuzu" | "neo4j" | "surrealql"
    capabilities: ClassVar[frozenset[str]]  # tiers this backend executes identically
    read_only_execution: ClassVar[bool]  # True if it enforces a read-only session (gate #2)

    async def run_query(self, ast: QueryAst, settings: QuerySettings) -> ResultTable: ...
