"""Always-on (no live server) checks for the ENH-004 server adapters: they
register, import, and their pure helpers behave. The behavioural conformance
runs against live containers — see test_neo4j_conformance / test_pgvector_conformance.
"""

from __future__ import annotations

import pytest

from agentforge_graph.store.neo4j_store import Neo4jGraphStore
from agentforge_graph.store.pgvector_store import PgVectorStore, _check_filter, _sym_path
from agentforge_graph.store.registry import graph_driver, vector_driver


def test_server_drivers_registered() -> None:
    assert graph_driver("neo4j") is Neo4jGraphStore
    assert vector_driver("pgvector") is PgVectorStore


def test_pgvector_filter_validation() -> None:
    _check_filter({"ref": "x", "kind": "Chunk", "path": "a.py"})  # allowed columns: no raise
    with pytest.raises(ValueError, match="unfilterable"):
        _check_filter({"ordinal": 0})


def test_pgvector_sym_path_from_ref() -> None:
    # path is derived from the ref's SymbolID, mirroring the graph adapter
    assert _sym_path("not a symbol id") == ""


def test_rowmap_roundtrips_unknown_kind_and_span() -> None:
    # the shared property mapping (Kuzu + Neo4j) round-trips an arbitrary kind
    # and tolerates an absent span (Neo4j drops null properties).
    from agentforge_graph.core import Node as GNode
    from agentforge_graph.core import NodeKind, Provenance
    from agentforge_graph.store._rowmap import node_from_row, node_params

    sym = "ckg py r src/a.py Foo#"
    node = GNode(id=sym, kind=NodeKind.CLASS, name="Foo", provenance=Provenance.parsed("x"))
    params = node_params(node, origin_path="src/a.py")
    del params["span_start"], params["span_end"]  # simulate Neo4j null-drop
    back = node_from_row(params)
    assert back.id == sym
    assert back.kind is NodeKind.CLASS
    assert back.span is None
