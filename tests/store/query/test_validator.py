"""Validator unit tests (feat-015 chunk 1): the trust boundary.

Phase 1 (backend-independent): vocabulary + exclusions. Phase 2: capability
tiers. A valid query returns unchanged; every rule has a rejecting case.
"""

from __future__ import annotations

import pytest

from agentforge_graph.store.query import (
    CapabilityError,
    ValidationError,
    parse_query,
    validate_query,
)
from agentforge_graph.store.query.capability import (
    AGG_COLLECT,
    CORE_TIER,
)


def _v(text: str, capabilities: frozenset[str] = CORE_TIER) -> None:
    validate_query(parse_query(text), capabilities)


# --- valid queries ----------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "MATCH (f:Function) RETURN f.name",
        'MATCH (c:Class {name: "Repo"}) RETURN c.path',
        "MATCH (a:Class)-[:IMPLEMENTS]->(i:Interface) RETURN i.name, count(a) AS n ORDER BY n DESC",
        "MATCH (f:Function) WHERE NOT (f)<-[:CALLS]-() RETURN f.name",
        "MATCH (f:Function)-[:CALLS*1..3]->(g:Function) RETURN g.name",
        "MATCH (a:Class)-[:IMPLEMENTS]->(i:Interface), (a)-[:INHERITS]->(b:Class) RETURN a.name",
    ],
)
def test_valid_queries_pass(text: str) -> None:
    _v(text)  # does not raise


def test_returns_ast_unchanged() -> None:
    ast = parse_query("MATCH (f:Function) RETURN f.name")
    assert validate_query(ast) is ast


# --- vocabulary -------------------------------------------------------------


def test_unknown_node_label_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown node label"):
        _v("MATCH (x:Widget) RETURN x.name")


def test_unknown_edge_kind_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown relationship type"):
        _v("MATCH (a:Class)-[:FROBS]->(b:Class) RETURN a.name")


def test_unknown_property_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown property"):
        _v("MATCH (f:Function) RETURN f.bogus")


def test_attrs_property_structurally_known_but_gated() -> None:
    # attrs.* parses and is a known property shape, but needs the (optional)
    # attrs.access capability, which the core tier does not include.
    from agentforge_graph.store.query.capability import ATTRS_ACCESS

    with pytest.raises(CapabilityError) as exc:
        _v('MATCH (f:Function) WHERE f.attrs.anything = "x" RETURN f.name')
    assert exc.value.capability == ATTRS_ACCESS


def test_attrs_property_allowed_when_backend_advertises_it() -> None:
    from agentforge_graph.store.query.capability import ATTRS_ACCESS

    _v(
        'MATCH (f:Function) WHERE f.attrs.anything = "x" RETURN f.name',
        capabilities=CORE_TIER | {ATTRS_ACCESS},
    )


def test_unknown_inline_property_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown inline property"):
        _v('MATCH (f:Function {bogus: "x"}) RETURN f.name')


def test_unbound_variable_in_return_rejected() -> None:
    with pytest.raises(ValidationError, match="not bound"):
        _v("MATCH (f:Function) RETURN g.name")


def test_unbound_variable_in_where_rejected() -> None:
    with pytest.raises(ValidationError, match="not bound"):
        _v('MATCH (f:Function) WHERE g.name = "x" RETURN f.name')


def test_order_by_alias_is_allowed() -> None:
    _v("MATCH (c:Class)-[:IMPLEMENTS]->(i:Interface) RETURN i.name, count(c) AS n ORDER BY n DESC")


def test_order_by_unknown_ref_rejected() -> None:
    with pytest.raises(ValidationError, match="ORDER BY"):
        _v("MATCH (f:Function) RETURN f.name ORDER BY nope DESC")


# --- exclusions -------------------------------------------------------------


def test_unbounded_varlen_rejected() -> None:
    with pytest.raises(ValidationError, match="unbounded variable-length"):
        _v("MATCH (f:Function)-[:CALLS*]->(g:Function) RETURN g.name")


def test_open_ended_varlen_rejected() -> None:
    with pytest.raises(ValidationError, match="unbounded variable-length"):
        _v("MATCH (f:Function)-[:CALLS*2..]->(g:Function) RETURN g.name")


def test_inverted_varlen_bounds_rejected() -> None:
    with pytest.raises(ValidationError, match="min <= max"):
        _v("MATCH (f:Function)-[:CALLS*5..2]->(g:Function) RETURN g.name")


def test_cartesian_product_rejected() -> None:
    with pytest.raises(ValidationError, match="Cartesian"):
        _v("MATCH (a:Class), (b:Interface) RETURN a.name, b.name")


def test_joined_multi_pattern_allowed_via_shared_var() -> None:
    # 'a' appears in both patterns => connected, not a Cartesian product.
    _v("MATCH (a:Class)-[:IMPLEMENTS]->(i:Interface), (a)-[:INHERITS]->(b:Class) RETURN a.name")


def test_disconnected_patterns_rejected_even_with_where() -> None:
    # A WHERE cannot join disconnected patterns (RHS is a literal, not a
    # property), so this is still a Cartesian product.
    with pytest.raises(ValidationError, match="Cartesian"):
        _v('MATCH (a:Class), (b:Interface) WHERE a.name = "x" RETURN a.name, b.name')


# --- capability tiers -------------------------------------------------------


def test_collect_rejected_without_capability() -> None:
    # collect() needs agg.collect, which the core tier does not include.
    with pytest.raises(CapabilityError) as exc:
        _v("MATCH (c:Class)-[:IMPLEMENTS]->(i:Interface) RETURN i.name, collect(c) AS impls")
    assert exc.value.capability == AGG_COLLECT


def test_collect_allowed_when_backend_advertises_it() -> None:
    _v(
        "MATCH (c:Class)-[:IMPLEMENTS]->(i:Interface) RETURN i.name, collect(c) AS impls",
        capabilities=CORE_TIER | {AGG_COLLECT},
    )


def test_capability_error_is_a_validation_error() -> None:
    # Callers can catch both parse-time vocabulary and capability rejects as one.
    with pytest.raises(ValidationError):
        _v("MATCH (c:Class) RETURN collect(c) AS x")


def test_varlen_requires_path_capability() -> None:
    empty: frozenset[str] = frozenset({"core", "agg.basic", "pattern.exists", "string.pred"})
    with pytest.raises(CapabilityError):
        _v("MATCH (f:Function)-[:CALLS*1..3]->(g:Function) RETURN g.name", capabilities=empty)
