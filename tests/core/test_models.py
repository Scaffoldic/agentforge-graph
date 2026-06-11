from __future__ import annotations

import pytest

from agentforge_graph.core import (
    Edge,
    EdgeKind,
    FileSubgraph,
    GraphQuery,
    Node,
    NodeKind,
    Provenance,
    QueryResult,
    SourceFile,
    SymbolID,
)

_PROV = Provenance.parsed("test")


def _sid(desc: str = "f().") -> str:
    return SymbolID.for_symbol("py", "repo", "a.py", desc)


def test_node_accepts_valid_symbol_id() -> None:
    n = Node(id=_sid(), kind=NodeKind.FUNCTION, name="f", provenance=_PROV)
    assert n.kind is NodeKind.FUNCTION


def test_node_rejects_malformed_id() -> None:
    with pytest.raises(ValueError, match="malformed|scheme"):
        Node(id="garbage", kind=NodeKind.FUNCTION, name="f", provenance=_PROV)


def test_edge_validates_both_endpoints() -> None:
    e = Edge(src=_sid("a()."), dst=_sid("b()."), kind=EdgeKind.CALLS, provenance=_PROV)
    assert e.kind is EdgeKind.CALLS
    with pytest.raises(ValueError, match="malformed|scheme"):
        Edge(src=_sid(), dst="nope", kind=EdgeKind.CALLS, provenance=_PROV)


def test_graphquery_limit_must_be_positive() -> None:
    assert GraphQuery(limit=5).limit == 5
    with pytest.raises(ValueError, match="limit"):
        GraphQuery(limit=0)


def test_filesubgraph_defaults_empty() -> None:
    sg = FileSubgraph(path="a.py", content_hash="h")
    assert sg.nodes == []
    assert sg.edges == []


def test_queryresult_defaults() -> None:
    r = QueryResult()
    assert r.nodes == [] and r.edges == [] and r.truncated is False


def test_sourcefile_is_frozen() -> None:
    f = SourceFile(path="a.py", text="x", language="py", content_hash="h")
    with pytest.raises(ValueError):
        f.text = "y"  # type: ignore[misc]
