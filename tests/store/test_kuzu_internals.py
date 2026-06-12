"""Kuzu-adapter internals beyond the shared conformance suite: value
round-tripping, every GraphQuery filter, truncation, neighbor depth,
persistence across reopen, and the MERGE-keeps-enrichment-edges guarantee.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import (
    Edge,
    EdgeKind,
    FileSubgraph,
    GraphQuery,
    Node,
    NodeKind,
    Provenance,
    Source,
    SymbolID,
)
from agentforge_graph.core.conformance import make_sample_subgraph
from agentforge_graph.core.symbols import Descriptor
from agentforge_graph.store import KuzuGraphStore

_LANG, _REPO, _PATH = "py", "sample", "src/app/auth.py"


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[KuzuGraphStore]:
    s = await KuzuGraphStore.open(tmp_path / "graph.kuzu")
    try:
        yield s
    finally:
        await s.close()


async def test_attrs_and_span_round_trip(store: KuzuGraphStore) -> None:
    nid = SymbolID.for_symbol(_LANG, _REPO, _PATH, Descriptor.type("Auth"))
    node = Node(
        id=nid,
        kind=NodeKind.CLASS,
        name="Auth",
        span=(3, 42),
        attrs={"decorators": ["@final"], "nesting": 2, "abstract": False},
        provenance=Provenance.parsed("t"),
    )
    await store.add([node])
    got = await store.get(nid)
    assert got is not None
    assert got.span == (3, 42)
    assert got.attrs == {"decorators": ["@final"], "nesting": 2, "abstract": False}
    assert got.provenance.source is Source.PARSED


async def test_query_filters(store: KuzuGraphStore) -> None:
    await store.upsert(make_sample_subgraph())
    # by kind
    classes = await store.query(GraphQuery(kinds=[NodeKind.CLASS]))
    assert {n.name for n in classes.nodes} == {"Auth"}
    # by exact name
    by_name = await store.query(GraphQuery(name="login"))
    assert len(by_name.nodes) == 1
    assert by_name.nodes[0].kind is NodeKind.METHOD
    # by path prefix
    pref = await store.query(GraphQuery(path_prefix="src/app"))
    assert len(pref.nodes) == 3
    assert (await store.query(GraphQuery(path_prefix="nope/"))).nodes == []


async def test_min_source_floor(store: KuzuGraphStore) -> None:
    await store.upsert(make_sample_subgraph())  # all parsed
    summary_id = SymbolID.for_symbol(_LANG, _REPO, _PATH, "Auth#summary.")
    await store.add(
        [Node(id=summary_id, kind=NodeKind.SUMMARY, name="s", provenance=Provenance.llm("e", 0.9))]
    )
    # floor=PARSED keeps only parsed nodes (drops the llm summary)
    parsed_only = await store.query(GraphQuery(min_source=Source.PARSED))
    assert summary_id not in {n.id for n in parsed_only.nodes}
    # floor=LLM keeps everything
    everything = await store.query(GraphQuery(min_source=Source.LLM, limit=100))
    assert summary_id in {n.id for n in everything.nodes}


async def test_query_truncation(store: KuzuGraphStore) -> None:
    prov = Provenance.parsed("t")
    nodes = [
        Node(
            id=SymbolID.for_symbol(_LANG, _REPO, f"f{i}.py", ""),
            kind=NodeKind.FILE,
            name=f"f{i}",
            provenance=prov,
        )
        for i in range(5)
    ]
    await store.add(list(nodes))
    res = await store.query(GraphQuery(limit=3))
    assert len(res.nodes) == 3
    assert res.truncated is True
    res_all = await store.query(GraphQuery(limit=5))
    assert res_all.truncated is False


async def test_neighbors_any_kind_and_depth(store: KuzuGraphStore) -> None:
    sg = make_sample_subgraph()
    await store.upsert(sg)
    file_id, class_id, method_id = (n.id for n in sg.nodes)
    # kinds=None walks any edge kind
    one = {n.id for n in await store.neighbors(class_id, None, depth=1)}
    assert one == {file_id, method_id}
    # depth caps the walk
    one_hop = {n.id for n in await store.neighbors(file_id, [EdgeKind.CONTAINS], depth=1)}
    assert method_id not in one_hop


async def test_enrichment_edge_survives_reupsert(store: KuzuGraphStore) -> None:
    sg = make_sample_subgraph()
    await store.upsert(sg)
    class_id = sg.nodes[1].id
    summary_id = SymbolID.for_symbol(_LANG, _REPO, _PATH, "Auth#summary.")
    llm = Provenance.llm("enricher", 0.9)
    await store.add(
        [
            Node(id=summary_id, kind=NodeKind.SUMMARY, name="summary", provenance=llm),
            Edge(src=summary_id, dst=class_id, kind=EdgeKind.SUMMARIZES, provenance=llm),
        ]
    )
    await store.upsert(make_sample_subgraph(commit="c1"))  # re-index the file
    # the edge — not just the node — must still connect summary -> class
    nbrs = {n.id for n in await store.neighbors(summary_id, [EdgeKind.SUMMARIZES], depth=1)}
    assert class_id in nbrs


async def test_stale_node_pruned_on_upsert(store: KuzuGraphStore) -> None:
    sg = make_sample_subgraph()
    await store.upsert(sg)
    method_id = sg.nodes[2].id
    # re-upsert a smaller subgraph for the same path (method gone)
    smaller = FileSubgraph(
        path=sg.path, content_hash="h2", nodes=sg.nodes[:2], edges=sg.edges[:1]
    )
    await store.upsert(smaller)
    assert await store.get(method_id) is None
    assert await store.get(sg.nodes[0].id) is not None


async def test_edge_to_absent_node_is_dropped(store: KuzuGraphStore) -> None:
    a = SymbolID.for_symbol(_LANG, _REPO, _PATH, Descriptor.type("A"))
    ghost = SymbolID.for_symbol(_LANG, _REPO, "other.py", Descriptor.type("Ghost"))
    prov = Provenance.parsed("t")
    await store.add([Node(id=a, kind=NodeKind.CLASS, name="A", provenance=prov)])
    # edge references a node that doesn't exist yet — MATCH drops it, no crash
    await store.add([Edge(src=a, dst=ghost, kind=EdgeKind.REFERENCES, provenance=prov)])
    assert await store.neighbors(a, [EdgeKind.REFERENCES], depth=1) == []


async def test_upsert_rolls_back_on_error(
    store: KuzuGraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    sg = make_sample_subgraph()
    await store.upsert(sg)  # seed committed state

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(store, "_insert_edge", boom)
    with pytest.raises(RuntimeError, match="boom"):
        await store.upsert(make_sample_subgraph(commit="c1"))
    # the connection survived ROLLBACK and the seeded node is still there
    assert await store.get(sg.nodes[0].id) is not None


async def test_persists_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "graph.kuzu"
    s1 = await KuzuGraphStore.open(path)
    sg = make_sample_subgraph()
    await s1.upsert(sg)
    await s1.close()
    await s1.close()  # idempotent
    s2 = await KuzuGraphStore.open(path)  # reopen: DDL "already exists" branch
    try:
        got = await s2.get(sg.nodes[0].id)
        assert got is not None
    finally:
        await s2.close()
