"""feat-009 chunk 2 — the retriever surfaces denormalised churn/authorship on
items (so ``ckg_symbol`` shows it) only when the symbol carries it."""

from __future__ import annotations

from agentforge_graph.core import NodeKind, Provenance, SymbolID
from agentforge_graph.core.models import Node
from agentforge_graph.retrieve.pack import ContextItem
from agentforge_graph.retrieve.retriever import _temporal_attrs

_ID = SymbolID.for_symbol("py", "sample", "m.py", "alpha().")


def _node(attrs: dict) -> Node:
    return Node(
        id=_ID,
        kind=NodeKind.FUNCTION,
        name="alpha",
        span=(1, 3),
        attrs=attrs,
        provenance=Provenance.parsed("t"),
    )


def test_temporal_attrs_extracted_when_present() -> None:
    node = _node(
        {
            "code": "...",
            "signature": "alpha()",  # non-temporal keys ignored
            "churn_90d": 7,
            "introduced": "abc",
            "last_changed": "def",
            "top_authors": [{"name": "Ann", "commits": 2}],
        }
    )
    t = _temporal_attrs(node)
    assert t == {
        "churn_90d": 7,
        "introduced": "abc",
        "last_changed": "def",
        "top_authors": [{"name": "Ann", "commits": 2}],
    }


def test_temporal_attrs_none_when_absent() -> None:
    assert _temporal_attrs(_node({"code": "..."})) is None


def test_item_serializes_temporal() -> None:
    item = ContextItem(
        id=_ID,
        kind=NodeKind.FUNCTION,
        name="alpha",
        score=1.0,
        path="m.py",
        provenance=Provenance.parsed("t").source,
        temporal={"churn_90d": 7},
    )
    assert item.model_dump()["temporal"] == {"churn_90d": 7}
