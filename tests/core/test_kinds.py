from __future__ import annotations

from agentforge_graph.core import EdgeKind, NodeKind


def test_node_kinds_are_str_valued() -> None:
    assert NodeKind.FUNCTION == "Function"
    assert isinstance(NodeKind.CLASS.value, str)


def test_reserved_higher_level_kinds_present() -> None:
    # ADR-0005: producers ship later, but the kinds are locked at 0.1.
    for kind in ("Decision", "Route", "DataModel", "Service", "Summary", "PatternTag"):
        assert kind in {k.value for k in NodeKind}


def test_edge_kinds_unique() -> None:
    values = [e.value for e in EdgeKind]
    assert len(values) == len(set(values))
