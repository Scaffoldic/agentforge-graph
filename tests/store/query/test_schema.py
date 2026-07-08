"""Schema-introspection unit tests (feat-015 chunk 1).

The curated property catalogue must stay aligned with the shared physical row
schema (store/_rowmap.py) so every logical property maps to a real column on
every backend — this is what makes ``f.path`` portable.
"""

from __future__ import annotations

from agentforge_graph.core import EdgeKind, NodeKind
from agentforge_graph.store._rowmap import node_params
from agentforge_graph.store.query.schema import (
    NODE_PROPERTIES,
    QUERY_LANG_VERSION,
    describe_schema,
    is_attrs_ref,
    is_known_property,
)


def test_describe_schema_lists_all_kinds() -> None:
    desc = describe_schema()
    assert set(desc.node_kinds) == {k.value for k in NodeKind}
    assert set(desc.edge_kinds) == {k.value for k in EdgeKind}
    assert desc.lang_version == QUERY_LANG_VERSION


def test_to_dict_is_json_shaped() -> None:
    d = describe_schema().to_dict()
    assert d["query_lang_version"] == QUERY_LANG_VERSION
    assert "node_kinds" in d and "edge_kinds" in d
    assert all({"name", "type", "doc"} <= set(p) for p in d["node_properties"])


def test_every_property_maps_to_a_real_physical_column() -> None:
    # Build a representative node row and assert every curated property's backing
    # column actually exists in the shared row schema — no property promises a
    # column the backends don't persist.
    fixture = _sample_row()
    for spec in NODE_PROPERTIES:
        assert spec.column in fixture, f"{spec.name} -> {spec.column} missing from row schema"


def test_is_known_property() -> None:
    assert is_known_property(("name",))
    assert is_known_property(("path",))
    assert is_known_property(("attrs", "framework"))
    assert is_known_property(("attrs", "a", "b"))
    assert not is_known_property(("bogus",))
    assert not is_known_property(("attrs",))  # needs a key after attrs


def test_is_attrs_ref() -> None:
    assert is_attrs_ref(("attrs", "x"))
    assert not is_attrs_ref(("name",))
    assert not is_attrs_ref(("attrs",))


def _sample_row() -> dict[str, object]:
    from agentforge_graph.core import Descriptor, Node, NodeKind, Provenance, SymbolID

    node = Node(
        id=SymbolID.for_symbol("py", "repo", "pkg/mod.py", Descriptor.term("func")),
        kind=NodeKind.FUNCTION,
        name="func",
        span=(1, 10),
        provenance=Provenance.parsed("tree-sitter-python@0.23"),
    )
    return node_params(node, origin_path="pkg/mod.py")
