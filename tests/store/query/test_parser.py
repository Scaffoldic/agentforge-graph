"""Parser unit tests (feat-015 chunk 1): text -> QueryAst, syntax only.

Every supported construct parses to the expected AST; write verbs and other
out-of-grammar text raise ParseError. Vocabulary is *not* checked here (that is
the validator's job) — these tests assert shape, not meaning.
"""

from __future__ import annotations

import pytest

from agentforge_graph.store.query import ParseError, parse_query
from agentforge_graph.store.query.ast import (
    Aggregate,
    BoolOp,
    Compare,
    InList,
    Lit,
    NodePattern,
    Not,
    PatternExists,
    PropRef,
    RelPattern,
    StringPred,
    VarRef,
)


def test_minimal_match_return() -> None:
    ast = parse_query("MATCH (f:Function) RETURN f.name")
    assert len(ast.match) == 1
    (node,) = ast.match[0].elements
    assert node == NodePattern("f", "Function", ())
    assert ast.returns[0].expr == PropRef("f", ("name",))
    assert ast.returns[0].alias is None


def test_relationship_direction_out() -> None:
    ast = parse_query("MATCH (a:Class)-[:IMPLEMENTS]->(b:Interface) RETURN a.name")
    a, rel, b = ast.match[0].elements
    assert isinstance(rel, RelPattern)
    assert rel.kind == "IMPLEMENTS" and rel.direction == "out"
    assert isinstance(a, NodePattern) and isinstance(b, NodePattern)


def test_relationship_direction_in_and_anon_node() -> None:
    ast = parse_query("MATCH (f:Function)<-[:CALLS]-() RETURN f.name")
    f, rel, anon = ast.match[0].elements
    assert isinstance(rel, RelPattern) and rel.direction == "in" and rel.kind == "CALLS"
    assert anon == NodePattern(None, None, ())


def test_undirected_relationship() -> None:
    ast = parse_query("MATCH (a)-[:REFERENCES]-(b) RETURN a.name")
    _, rel, _ = ast.match[0].elements
    assert isinstance(rel, RelPattern) and rel.direction == "both"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("MATCH (f:Function)-[:CALLS*1..3]->(g) RETURN g.name", (1, 3)),
        ("MATCH (f:Function)-[:CALLS*2]->(g) RETURN g.name", (2, 2)),
        ("MATCH (f:Function)-[:CALLS*..4]->(g) RETURN g.name", (1, 4)),
    ],
)
def test_bounded_varlen(text: str, expected: tuple[int, int]) -> None:
    _, rel, _ = parse_query(text).match[0].elements
    assert isinstance(rel, RelPattern)
    assert (rel.min_hops, rel.max_hops) == expected


def test_unbounded_varlen_parses_with_none_maxhops() -> None:
    # The parser accepts it (syntax); the validator is what rejects it.
    _, rel, _ = parse_query("MATCH (f)-[:CALLS*]->(g) RETURN g.name").match[0].elements
    assert isinstance(rel, RelPattern) and rel.max_hops is None


def test_inline_props() -> None:
    ast = parse_query('MATCH (c:Class {name: "Repo"}) RETURN c.name')
    (node,) = ast.match[0].elements
    assert isinstance(node, NodePattern)
    assert node.props == (("name", Lit("Repo")),)


def test_where_comparisons_and_booleans() -> None:
    ast = parse_query(
        'MATCH (f:Function) WHERE f.confidence >= 0.5 AND f.name <> "x" RETURN f.name'
    )
    assert isinstance(ast.where, BoolOp) and ast.where.op == "AND"
    left, right = ast.where.operands
    assert left == Compare(PropRef("f", ("confidence",)), ">=", Lit(0.5))
    assert right == Compare(PropRef("f", ("name",)), "<>", Lit("x"))


def test_where_in_list() -> None:
    ast = parse_query('MATCH (n:Class) WHERE n.source IN ["parsed", "resolved"] RETURN n.name')
    assert ast.where == InList(PropRef("n", ("source",)), (Lit("parsed"), Lit("resolved")))


def test_where_string_predicates() -> None:
    ast = parse_query('MATCH (f:Function) WHERE f.path STARTS WITH "src/" RETURN f.name')
    assert ast.where == StringPred(PropRef("f", ("path",)), "STARTS_WITH", "src/")


def test_where_not_pattern_exists() -> None:
    ast = parse_query("MATCH (f:Function) WHERE NOT (f)<-[:CALLS]-() RETURN f.name, f.path")
    assert isinstance(ast.where, Not)
    assert isinstance(ast.where.operand, PatternExists)
    # two projections
    assert [i.expr for i in ast.returns] == [PropRef("f", ("name",)), PropRef("f", ("path",))]


def test_grouped_expr_not_mistaken_for_pattern() -> None:
    ast = parse_query('MATCH (f:Function) WHERE (f.name = "a" OR f.name = "b") RETURN f.name')
    assert isinstance(ast.where, BoolOp) and ast.where.op == "OR"


def test_attrs_property_path() -> None:
    ast = parse_query('MATCH (s:Service) WHERE s.attrs.framework = "fastapi" RETURN s.name')
    assert ast.where == Compare(PropRef("s", ("attrs", "framework")), "=", Lit("fastapi"))


def test_aggregate_with_alias_and_order_limit() -> None:
    ast = parse_query(
        "MATCH (c:Class)-[:IMPLEMENTS]->(i:Interface) "
        "RETURN i.name, count(c) AS impls ORDER BY impls DESC LIMIT 10"
    )
    agg_item = ast.returns[1]
    assert agg_item.expr == Aggregate("count", VarRef("c"), False)
    assert agg_item.alias == "impls"
    assert ast.order_by[0].descending is True
    assert ast.limit == 10


def test_count_star_and_distinct() -> None:
    ast = parse_query("MATCH (f:Function) RETURN DISTINCT count(*) AS n")
    assert ast.distinct is True
    assert ast.returns[0].expr == Aggregate("count", None, False)


def test_skip_and_limit() -> None:
    ast = parse_query("MATCH (f:Function) RETURN f.name SKIP 5 LIMIT 10")
    assert ast.skip == 5 and ast.limit == 10


def test_negative_number_literal() -> None:
    ast = parse_query("MATCH (n:Chunk) WHERE n.start_line > -1 RETURN n.name")
    assert ast.where == Compare(PropRef("n", ("start_line",)), ">", Lit(-1))


def test_multiple_comma_patterns() -> None:
    ast = parse_query('MATCH (a:Class), (b:Interface) WHERE a.name = "x" RETURN a.name')
    assert len(ast.match) == 2


@pytest.mark.parametrize(
    "text",
    [
        'CREATE (n:Class {name: "x"}) RETURN n.name',
        "MATCH (n:Class) SET n.name = 'y' RETURN n.name",
        "MATCH (n:Class) DELETE n",
        "MATCH (n:Class) DETACH DELETE n",
        "MATCH (n:Class) REMOVE n.name RETURN n",
        "CALL db.labels()",
        "MATCH (n:Class) WITH n RETURN n.name",
        "UNWIND [1,2,3] AS x RETURN x",
        "MERGE (n:Class) RETURN n",
    ],
)
def test_write_and_out_of_grammar_rejected(text: str) -> None:
    with pytest.raises(ParseError):
        parse_query(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "RETURN 1",  # no MATCH
        "MATCH (f:Function)",  # no RETURN
        "MATCH (f RETURN f.name",  # unbalanced paren
        "MATCH (f:Function) RETURN f.",  # dangling property
        "MATCH (f:Function)-[:CALLS>(g) RETURN g.name",  # malformed rel
        "MATCH (f:Function) RETURN f.name LIMIT",  # missing int
        "MATCH (a)<-[:X]->(b) RETURN a.name",  # both-way arrow
    ],
)
def test_malformed_queries_rejected(text: str) -> None:
    with pytest.raises(ParseError):
        parse_query(text)


def test_parse_error_carries_position() -> None:
    with pytest.raises(ParseError) as exc:
        parse_query("MATCH (f:Function) RETURN f.name LIMIT xyz")
    assert exc.value.position is not None
