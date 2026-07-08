"""The validator — the second (semantic) half of the trust boundary (feat-015).

The parser proves syntax; this proves *meaning* against the locked feat-001
vocabulary and the read-only exclusion rules, then (phase 2) against the target
backend's declared capabilities. A query that survives here is safe to compile.

Two phases, run in order:

1. **Backend-independent** — labels ∈ ``NodeKind``, rel types ∈ ``EdgeKind``,
   property refs are curated names or ``attrs.*``, every referenced variable is
   bound, no unbounded variable-length path, no un-joined Cartesian product.
2. **Capability** — each construct maps to a capability tier; a construct the
   target backend does not declare raises ``CapabilityError`` (a
   ``ValidationError`` subclass) naming what is supported. This is what lets the
   subset grow per-backend without ever silently diverging.
"""

from __future__ import annotations

from collections.abc import Iterator

from agentforge_graph.core import EdgeKind, NodeKind

from .ast import (
    Aggregate,
    BoolOp,
    Compare,
    Expr,
    InList,
    NodePattern,
    Not,
    PathPattern,
    PatternExists,
    PropRef,
    QueryAst,
    RelPattern,
    StringPred,
    VarRef,
)
from .capability import (
    AGG_BASIC,
    AGG_COLLECT,
    CORE_TIER,
    PATH_VARLEN,
    PATTERN_EXISTS,
    STRING_PRED,
)
from .errors import CapabilityError, ValidationError
from .schema import PROPERTY_BY_NAME, is_known_property

_NODE_KIND_VALUES = frozenset(k.value for k in NodeKind)
_EDGE_KIND_VALUES = frozenset(k.value for k in EdgeKind)


def validate_query(ast: QueryAst, capabilities: frozenset[str] = CORE_TIER) -> QueryAst:
    """Validate an AST against the vocabulary, the exclusion rules, and the
    target backend's ``capabilities``. Returns the AST unchanged on success;
    raises ``ValidationError`` / ``CapabilityError`` otherwise."""
    _check_vocabulary(ast)
    _check_exclusions(ast)
    _check_capabilities(ast, capabilities)
    return ast


# --- iteration helpers ------------------------------------------------------


def _all_patterns(ast: QueryAst) -> Iterator[PathPattern]:
    yield from ast.match
    if ast.where is not None:
        for e in _walk_expr(ast.where):
            if isinstance(e, PatternExists):
                yield e.pattern


def _walk_expr(expr: Expr) -> Iterator[Expr]:
    yield expr
    if isinstance(expr, BoolOp):
        for operand in expr.operands:
            yield from _walk_expr(operand)
    elif isinstance(expr, Not):
        yield from _walk_expr(expr.operand)


def _rels(ast: QueryAst) -> Iterator[RelPattern]:
    for pat in _all_patterns(ast):
        for el in pat.elements:
            if isinstance(el, RelPattern):
                yield el


def _nodes(ast: QueryAst) -> Iterator[NodePattern]:
    for pat in _all_patterns(ast):
        for el in pat.elements:
            if isinstance(el, NodePattern):
                yield el


def _where_prop_refs(ast: QueryAst) -> Iterator[PropRef]:
    if ast.where is None:
        return
    for e in _walk_expr(ast.where):
        if isinstance(e, (Compare, InList, StringPred)):
            yield e.lhs


def _return_prop_refs(ast: QueryAst) -> Iterator[PropRef]:
    for item in ast.returns:
        expr = item.expr
        if isinstance(expr, PropRef):
            yield expr
        elif isinstance(expr, Aggregate) and isinstance(expr.arg, PropRef):
            yield expr.arg


# --- phase 1: vocabulary ----------------------------------------------------


def _check_vocabulary(ast: QueryAst) -> None:
    for node in _nodes(ast):
        if node.label is not None and node.label not in _NODE_KIND_VALUES:
            raise ValidationError(
                f"unknown node label ':{node.label}'. Valid kinds: "
                f"{', '.join(sorted(_NODE_KIND_VALUES))}"
            )
        for key, _ in node.props:
            if key not in PROPERTY_BY_NAME:
                raise ValidationError(
                    f"unknown inline property '{key}'. Queryable properties: "
                    f"{', '.join(sorted(PROPERTY_BY_NAME))} (or attrs.<key>)"
                )
    for rel in _rels(ast):
        if rel.kind is not None and rel.kind not in _EDGE_KIND_VALUES:
            raise ValidationError(
                f"unknown relationship type ':{rel.kind}'. Valid kinds: "
                f"{', '.join(sorted(_EDGE_KIND_VALUES))}"
            )

    bound = _bound_vars(ast)
    return_aliases = {item.alias for item in ast.returns if item.alias}
    for ref in (*_where_prop_refs(ast), *_return_prop_refs(ast)):
        _check_property(ref)
        _require_bound(ref.var, bound)
    # RETURN/ORDER bare vars must be bound; ORDER may also name a RETURN alias.
    for item in ast.returns:
        if isinstance(item.expr, VarRef):
            _require_bound(item.expr.var, bound)
        elif isinstance(item.expr, Aggregate) and isinstance(item.expr.arg, VarRef):
            _require_bound(item.expr.arg.var, bound)
    for order_key in ast.order_by:
        if isinstance(order_key.ref, PropRef):
            _check_property(order_key.ref)
            _require_bound(order_key.ref.var, bound)
        elif order_key.ref.var not in bound and order_key.ref.var not in return_aliases:
            raise ValidationError(
                f"ORDER BY references '{order_key.ref.var}', which is not a bound "
                f"variable or a RETURN alias"
            )


def _require_bound(var: str, bound: set[str]) -> None:
    if var not in bound:
        raise ValidationError(f"variable '{var}' is not bound in the MATCH clause")


def _check_property(ref: PropRef) -> None:
    if not is_known_property(ref.path):
        raise ValidationError(
            f"unknown property '{ref.var}.{'.'.join(ref.path)}'. Queryable properties: "
            f"{', '.join(sorted(PROPERTY_BY_NAME))} (or attrs.<key>)"
        )


def _bound_vars(ast: QueryAst) -> set[str]:
    bound: set[str] = set()
    for pat in _all_patterns(ast):
        for el in pat.elements:
            if el.var is not None:
                bound.add(el.var)
    return bound


# --- phase 1: exclusions ----------------------------------------------------


def _check_exclusions(ast: QueryAst) -> None:
    for rel in _rels(ast):
        if rel.max_hops is None:
            raise ValidationError(
                "unbounded variable-length path is not allowed; give an upper bound, "
                "e.g. [:CALLS*1..3]"
            )
        if rel.min_hops < 1 or rel.max_hops < rel.min_hops:
            raise ValidationError(
                f"invalid path length *{rel.min_hops}..{rel.max_hops}: need 1 <= min <= max"
            )
    if ast.skip is not None and ast.skip < 0:
        raise ValidationError("SKIP must be non-negative")
    if ast.limit is not None and ast.limit < 0:
        raise ValidationError("LIMIT must be non-negative")
    _check_cartesian(ast)


def _check_cartesian(ast: QueryAst) -> None:
    # Multiple top-level MATCH patterns must form one connected graph via shared
    # variables; otherwise they cross-product. A WHERE cannot join them — a
    # comparison's right side is a literal (parameterized), never another
    # property — so connectivity is checked structurally, not via WHERE.
    if len(ast.match) < 2:
        return
    var_sets = [{el.var for el in pat.elements if el.var is not None} for pat in ast.match]
    parent = list(range(len(var_sets)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(var_sets)):
        for j in range(i + 1, len(var_sets)):
            if var_sets[i] & var_sets[j]:
                parent[find(i)] = find(j)
    if len({find(i) for i in range(len(var_sets))}) > 1:
        raise ValidationError(
            "disconnected MATCH patterns form a Cartesian product; connect them "
            "with a shared variable"
        )


# --- phase 2: capability ----------------------------------------------------


def _check_capabilities(ast: QueryAst, capabilities: frozenset[str]) -> None:
    required: set[str] = set()
    for rel in _rels(ast):
        if (rel.min_hops, rel.max_hops) != (1, 1):
            required.add(PATH_VARLEN)
    if ast.where is not None:
        for e in _walk_expr(ast.where):
            if isinstance(e, StringPred):
                required.add(STRING_PRED)
            elif isinstance(e, PatternExists):
                required.add(PATTERN_EXISTS)
    for item in ast.returns:
        if isinstance(item.expr, Aggregate):
            required.add(AGG_COLLECT if item.expr.func == "collect" else AGG_BASIC)
    for cap in sorted(required):
        if cap not in capabilities:
            raise CapabilityError(cap, capabilities)
