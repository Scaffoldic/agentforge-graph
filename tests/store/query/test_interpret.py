"""Targeted unit tests for the AST interpreter (feat-015 chunk 4).

The conformance suite covers the core parity path; these cover the branches it
doesn't: avg/min/max/collect aggregates, DISTINCT, ORDER BY a property, attrs
access, node_property fields, and the timeout backstop. Driven over an embedded
Kuzu store as the data source.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import (
    Descriptor,
    Edge,
    EdgeKind,
    FileSubgraph,
    Node,
    NodeKind,
    Provenance,
    SymbolID,
)
from agentforge_graph.store import KuzuGraphStore
from agentforge_graph.store.query import parse_query, validate_query
from agentforge_graph.store.query.capability import ATTRS_ACCESS, CORE_TIER, QuerySettings
from agentforge_graph.store.query.interpret import InterpretingQueryEngine, node_property

_PROV = Provenance.parsed("interp-test", "c0")
_CAPS = CORE_TIER | {ATTRS_ACCESS, "agg.collect"}


def _n(desc: str, kind: NodeKind, name: str, span: tuple[int, int], **attrs: object) -> Node:
    return Node(
        id=SymbolID.for_symbol("py", "r", "a.py", desc),
        kind=kind,
        name=name,
        span=span,
        attrs=attrs,
        provenance=_PROV,
    )


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[KuzuGraphStore]:
    s = await KuzuGraphStore.open(tmp_path / "g.kuzu")
    cls = _n(Descriptor.type("Svc"), NodeKind.CLASS, "Svc", (1, 40), layer="core")
    other = _n(Descriptor.type("Web"), NodeKind.CLASS, "Web", (2, 5), layer="ui")
    m1 = _n(Descriptor.type("Svc") + Descriptor.method("a"), NodeKind.METHOD, "a", (3, 8))
    m2 = _n(Descriptor.type("Svc") + Descriptor.method("b"), NodeKind.METHOD, "b", (10, 20))
    nodes = [cls, other, m1, m2]
    edges = [
        Edge(src=cls.id, dst=m1.id, kind=EdgeKind.CONTAINS, provenance=_PROV),
        Edge(src=cls.id, dst=m2.id, kind=EdgeKind.CONTAINS, provenance=_PROV),
    ]
    await s.upsert(FileSubgraph(path="a.py", content_hash="h", nodes=nodes, edges=edges))
    try:
        yield s
    finally:
        await s.close()


async def _run(store: KuzuGraphStore, text: str, settings: QuerySettings | None = None):
    ast = validate_query(parse_query(text), _CAPS)
    return await InterpretingQueryEngine(store).run(ast, settings or QuerySettings())


async def test_avg_min_max_aggregates(store: KuzuGraphStore) -> None:
    rt = await _run(
        store,
        "MATCH (m:Method) RETURN min(m.start_line) AS lo, max(m.end_line) AS hi, "
        "avg(m.start_line) AS mid",
    )
    assert rt.columns == ("lo", "hi", "mid")
    assert rt.rows == ((3, 20, 6.5),)


async def test_collect_is_sorted(store: KuzuGraphStore) -> None:
    rt = await _run(
        store,
        "MATCH (c:Class)-[:CONTAINS]->(m:Method) RETURN c.name, collect(m.name) AS ms",
    )
    assert rt.rows == (("Svc", ["a", "b"]),)


async def test_distinct(store: KuzuGraphStore) -> None:
    rt = await _run(store, "MATCH (c:Class) RETURN DISTINCT c.kind")
    assert rt.rows == (("Class",),)


async def test_order_by_property_desc(store: KuzuGraphStore) -> None:
    rt = await _run(store, "MATCH (m:Method) RETURN m.name ORDER BY m.start_line DESC")
    assert [r[0] for r in rt.rows] == ["b", "a"]  # start_line 10 then 3


async def test_attrs_access_when_permitted(store: KuzuGraphStore) -> None:
    rt = await _run(store, 'MATCH (c:Class) WHERE c.attrs.layer = "core" RETURN c.name')
    assert {r[0] for r in rt.rows} == {"Svc"}


async def test_timeout_backstop_reports_partial(store: KuzuGraphStore) -> None:
    # a clock that jumps past the deadline after the first binding is appended
    import contextlib

    ticks = iter([0.0, 100.0, 100.0, 100.0, 100.0])
    last = [0.0]

    def now() -> float:
        with contextlib.suppress(StopIteration):
            last[0] = next(ticks)
        return last[0]

    ast = validate_query(parse_query("MATCH (c:Class) RETURN c.name"), _CAPS)
    rt = await InterpretingQueryEngine(store).run(ast, QuerySettings(timeout_ms=1000), now=now)
    assert rt.truncated and rt.stopped_reason == "timeout"


def test_node_property_covers_all_fields() -> None:
    n = _n(Descriptor.term("f"), NodeKind.FUNCTION, "f", (2, 9), role="svc")
    assert node_property(n, ("name",)) == "f"
    assert node_property(n, ("kind",)) == "Function"
    assert node_property(n, ("path",)) == "a.py"
    assert node_property(n, ("start_line",)) == 2
    assert node_property(n, ("end_line",)) == 9
    assert node_property(n, ("source",)) == "parsed"
    assert node_property(n, ("extractor",)) == "interp-test"
    assert node_property(n, ("commit",)) == "c0"
    assert node_property(n, ("confidence",)) == 1.0
    assert node_property(n, ("attrs", "role")) == "svc"
    assert node_property(n, ("attrs", "missing")) is None
    assert node_property(n, ("bogus",)) is None
