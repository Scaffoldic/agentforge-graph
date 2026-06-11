"""Reusable conformance suites for the core ABCs.

A feat-003 storage adapter or a feat-002 extractor proves it honours
the contract by subclassing the matching ``*Conformance`` base class and
providing the required fixture. The same suite runs against every
implementer, so they're interchangeable. Pytest-free at import time (the
async test methods are collected by pytest-asyncio in the *test* package;
this module never imports pytest, keeping the core import light).
"""

from __future__ import annotations

from .contracts import Extractor, GraphStore
from .kinds import EdgeKind, NodeKind
from .models import Edge, FileSubgraph, GraphQuery, Node, SourceFile
from .provenance import Provenance
from .symbols import Descriptor, SymbolID

_LANG = "py"
_REPO = "sample"
_PATH = "src/app/auth.py"


def make_sample_subgraph(commit: str = "c0") -> FileSubgraph:
    """A tiny but valid subgraph: File ▸ Class ▸ Method, with CONTAINS."""
    prov = Provenance.parsed("conformance", commit)
    file_id = SymbolID.for_symbol(_LANG, _REPO, _PATH, "")
    class_id = SymbolID.for_symbol(_LANG, _REPO, _PATH, Descriptor.type("Auth"))
    method_id = SymbolID.for_symbol(
        _LANG, _REPO, _PATH, Descriptor.type("Auth") + Descriptor.method("login")
    )
    nodes = [
        Node(id=file_id, kind=NodeKind.FILE, name="auth.py", provenance=prov),
        Node(id=class_id, kind=NodeKind.CLASS, name="Auth", span=(1, 20), provenance=prov),
        Node(id=method_id, kind=NodeKind.METHOD, name="login", span=(2, 10), provenance=prov),
    ]
    edges = [
        Edge(src=file_id, dst=class_id, kind=EdgeKind.CONTAINS, provenance=prov),
        Edge(src=class_id, dst=method_id, kind=EdgeKind.CONTAINS, provenance=prov),
    ]
    return FileSubgraph(path=_PATH, content_hash=f"hash-{commit}", nodes=nodes, edges=edges)


class GraphStoreConformance:
    """Subclass in a feat-003 adapter; provide an async ``store`` fixture
    yielding a fresh, empty ``GraphStore``."""

    async def test_upsert_then_get(self, store: GraphStore) -> None:
        sg = make_sample_subgraph()
        await store.upsert(sg)
        got = await store.get(sg.nodes[0].id)
        assert got is not None
        assert got.id == sg.nodes[0].id

    async def test_reupsert_is_idempotent(self, store: GraphStore) -> None:
        sg = make_sample_subgraph()
        await store.upsert(sg)
        await store.upsert(sg)
        res = await store.query(GraphQuery(path_prefix="src/app"))
        assert len(res.nodes) == len(sg.nodes)

    async def test_delete_file_removes_nodes(self, store: GraphStore) -> None:
        sg = make_sample_subgraph()
        await store.upsert(sg)
        await store.delete_file(sg.path)
        assert await store.get(sg.nodes[0].id) is None

    async def test_enrichment_survives_file_reupsert(self, store: GraphStore) -> None:
        sg = make_sample_subgraph()
        await store.upsert(sg)
        target = sg.nodes[1].id  # the class
        summary_id = SymbolID.for_symbol(_LANG, _REPO, _PATH, "Auth#summary.")
        llm = Provenance.llm("enricher", 0.9)
        await store.add(
            [
                Node(id=summary_id, kind=NodeKind.SUMMARY, name="summary", provenance=llm),
                Edge(src=summary_id, dst=target, kind=EdgeKind.SUMMARIZES, provenance=llm),
            ]
        )
        # the file changes and is re-indexed; the enrichment must survive
        await store.upsert(make_sample_subgraph(commit="c1"))
        assert await store.get(summary_id) is not None

    async def test_reserved_kind_preserved(self, store: GraphStore) -> None:
        route_id = SymbolID.for_symbol(_LANG, _REPO, "src/app/api.py", "route(GET_x).")
        await store.add(
            [
                Node(
                    id=route_id,
                    kind=NodeKind.ROUTE,
                    name="GET /x",
                    provenance=Provenance.parsed("conformance"),
                )
            ]
        )
        got = await store.get(route_id)
        assert got is not None
        assert got.kind is NodeKind.ROUTE

    async def test_neighbors_walks_contains(self, store: GraphStore) -> None:
        sg = make_sample_subgraph()
        await store.upsert(sg)
        file_id, class_id, method_id = (n.id for n in sg.nodes)
        one_hop = {n.id for n in await store.neighbors(file_id, [EdgeKind.CONTAINS], depth=1)}
        assert class_id in one_hop
        two_hop = {n.id for n in await store.neighbors(file_id, [EdgeKind.CONTAINS], depth=2)}
        assert method_id in two_hop


class ExtractorConformance:
    """Subclass in a feat-002/011 pack; provide ``extractor`` and
    ``sample_file`` fixtures."""

    def test_output_is_valid_subgraph(self, extractor: Extractor, sample_file: SourceFile) -> None:
        sg = extractor.extract(sample_file)
        assert isinstance(sg, FileSubgraph)
        assert sg.path
        assert sg.content_hash

    def test_extraction_is_deterministic(
        self, extractor: Extractor, sample_file: SourceFile
    ) -> None:
        first = extractor.extract(sample_file)
        second = extractor.extract(sample_file)
        assert first.model_dump() == second.model_dump()
