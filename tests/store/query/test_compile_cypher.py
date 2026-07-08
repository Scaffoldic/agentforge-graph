"""Cypher compiler unit tests (feat-015 chunk 2): AST -> Cypher text + params.

Pure (no DB). Asserts the single-table mapping, property->column mapping, literal
parameterization, and the row-cap LIMIT. End-to-end execution is covered by the
Kuzu conformance suite.
"""

from __future__ import annotations

from agentforge_graph.store.query import parse_query, validate_query
from agentforge_graph.store.query.capability import AGG_COLLECT, CORE_TIER, QuerySettings
from agentforge_graph.store.query.compile_cypher import KuzuCypherCompiler

_CAPS = CORE_TIER | {AGG_COLLECT}


def _compile(text: str, max_rows: int = 1000):
    ast = validate_query(parse_query(text), _CAPS)
    return KuzuCypherCompiler().compile(ast, QuerySettings(max_rows=max_rows))


def test_label_maps_to_kind_predicate_inline() -> None:
    cq = _compile("MATCH (f:Function) RETURN f.name")
    assert "(f:CkgNode {kind: $p0})" in cq.text
    assert cq.params == {"p0": "Function"}
    assert cq.columns == ("f.name",)


def test_property_maps_to_physical_column() -> None:
    cq = _compile('MATCH (c:Class {name: "Repo"}) RETURN c.path, c.start_line')
    assert "c.sym_path" in cq.text and "c.span_start" in cq.text
    assert cq.columns == ("c.path", "c.start_line")


def test_literals_are_parameterized_never_spliced() -> None:
    cq = _compile('MATCH (f:Function) WHERE f.name = "x" AND f.confidence >= 0.5 RETURN f.name')
    assert '"x"' not in cq.text and "0.5" not in cq.text
    assert "x" in cq.params.values() and 0.5 in cq.params.values()


def test_relationship_and_direction() -> None:
    cq = _compile("MATCH (a:Class)-[:IMPLEMENTS]->(i:Interface) RETURN a.name")
    assert "-[:CkgEdge {kind: $" in cq.text and "]->" in cq.text


def test_varlen_span_rendered() -> None:
    cq = _compile("MATCH (f:Function)-[:CALLS*1..3]->(g:Function) RETURN g.name")
    assert "CkgEdge*1..3" in cq.text


def test_aggregate_over_node_var_uses_id() -> None:
    cq = _compile("MATCH (c:Class)-[:IMPLEMENTS]->(i:Interface) RETURN i.name, count(c) AS impls")
    assert "count(c.id) AS impls" in cq.text
    assert cq.columns == ("i.name", "impls")


def test_row_cap_limit_is_effective_plus_one() -> None:
    assert " LIMIT 6" in _compile("MATCH (f:Function) RETURN f.name", max_rows=5).text
    # caller LIMIT below the cap wins:
    assert " LIMIT 4" in _compile("MATCH (f:Function) RETURN f.name LIMIT 3", max_rows=5).text


def test_repeated_variable_declared_once() -> None:
    cq = _compile(
        "MATCH (a:Class)-[:IMPLEMENTS]->(i:Interface), (a)-[:INHERITS]->(b:Class) RETURN a.name"
    )
    # 'a' gets its label/kind once; the second occurrence is a bare reference.
    assert cq.text.count("a:CkgNode {kind:") == 1
    assert "(a)-[:CkgEdge {kind: $" in cq.text
