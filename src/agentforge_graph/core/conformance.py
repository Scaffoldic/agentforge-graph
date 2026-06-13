"""Reusable conformance suites for the core ABCs.

A feat-003 storage adapter or a feat-002 extractor proves it honours
the contract by subclassing the matching ``*Conformance`` base class and
providing the required fixture. The same suite runs against every
implementer, so they're interchangeable. Pytest-free at import time (the
async test methods are collected by pytest-asyncio in the *test* package;
this module never imports pytest, keeping the core import light).
"""

from __future__ import annotations

from .contracts import Extractor, GraphStore, VectorStore
from .kinds import EdgeKind, NodeKind
from .models import Edge, Embedded, FileSubgraph, GraphQuery, Node, SourceFile
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

    async def test_clear_resolved_invalidates_and_gcs_packages(self, store: GraphStore) -> None:
        sg = make_sample_subgraph()
        await store.upsert(sg)
        caller = sg.nodes[2].id  # the method, in _PATH
        # A resolved CALLS edge to a parsed symbol + a resolved IMPORTS edge to
        # an external package stub, both owned by _PATH (feat-004 tagging).
        pkg_id = SymbolID.for_symbol(_LANG, _REPO, "<external>", "react/namespace.")
        resolved = Provenance.resolved("resolver")
        await store.add(
            [
                Node(id=pkg_id, kind=NodeKind.PACKAGE, name="react", provenance=resolved),
                Edge(
                    src=caller,
                    dst=sg.nodes[1].id,
                    kind=EdgeKind.CALLS,
                    provenance=resolved,
                    origin_path=_PATH,
                ),
                Edge(
                    src=SymbolID.for_symbol(_LANG, _REPO, _PATH, ""),
                    dst=pkg_id,
                    kind=EdgeKind.IMPORTS,
                    provenance=resolved,
                    origin_path=_PATH,
                ),
            ]
        )
        assert await store.get(pkg_id) is not None
        await store.clear_resolved([_PATH])
        # resolved edges gone, the now-orphan package GC'd, parsed nodes intact
        assert await store.adjacent(caller, [EdgeKind.CALLS], "out") == []
        assert await store.get(pkg_id) is None
        assert await store.get(sg.nodes[1].id) is not None  # the class survives

    async def test_adjacent_directed(self, store: GraphStore) -> None:
        sg = make_sample_subgraph()  # File -CONTAINS-> Class -CONTAINS-> Method
        await store.upsert(sg)
        file_id, class_id, method_id = (n.id for n in sg.nodes)
        out = await store.adjacent(class_id, [EdgeKind.CONTAINS], "out")
        assert [(e.src, e.dst) for e in out] == [(class_id, method_id)]
        incoming = await store.adjacent(class_id, [EdgeKind.CONTAINS], "in")
        assert [(e.src, e.dst) for e in incoming] == [(file_id, class_id)]
        both = await store.adjacent(class_id, [EdgeKind.CONTAINS], "both")
        assert {(e.src, e.dst) for e in both} == {(file_id, class_id), (class_id, method_id)}
        # kind filter excludes non-matching edges
        assert await store.adjacent(class_id, [EdgeKind.CALLS], "both") == []


# Distinct kinds so a kind-filter discriminates; refs are valid SymbolIDs.
_SAMPLE_KINDS = (NodeKind.CHUNK, NodeKind.DOC_CHUNK, NodeKind.SUMMARY)


def make_sample_embeddings(dim: int = 8) -> list[Embedded]:
    """Three tiny one-hot vectors of dimension ``dim`` over distinct kinds,
    for exercising a ``VectorStore`` without a real embedder."""
    base = SymbolID.for_symbol(_LANG, _REPO, _PATH, Descriptor.type("Auth"))
    return [
        Embedded(
            ref=f"{base}chunk{i}.",
            vector=[1.0 if j == i else 0.0 for j in range(dim)],
            kind=_SAMPLE_KINDS[i],
            attrs={"ordinal": i},
        )
        for i in range(3)
    ]


class VectorStoreConformance:
    """Subclass in a feat-003 vector adapter; provide an async ``vectors``
    fixture yielding a fresh, empty ``VectorStore``.

    The ``filter`` contract targets first-class columns (``ref``, ``kind``,
    ``path``) — the portable subset every backend can honour — not nested
    ``attrs`` keys."""

    async def test_upsert_then_search_finds_nearest(self, vectors: VectorStore) -> None:
        items = make_sample_embeddings()
        await vectors.upsert(items)
        hits = await vectors.search(items[1].vector, k=1)
        assert hits
        assert hits[0].ref == items[1].ref

    async def test_reupsert_is_idempotent(self, vectors: VectorStore) -> None:
        items = make_sample_embeddings()
        await vectors.upsert(items)
        await vectors.upsert(items)
        hits = await vectors.search(items[0].vector, k=10)
        assert len({h.ref for h in hits}) == len(items)

    async def test_search_respects_k(self, vectors: VectorStore) -> None:
        items = make_sample_embeddings()
        await vectors.upsert(items)
        hits = await vectors.search(items[0].vector, k=2)
        assert len(hits) <= 2

    async def test_filter_constrains_results(self, vectors: VectorStore) -> None:
        items = make_sample_embeddings()
        await vectors.upsert(items)
        hits = await vectors.search(items[0].vector, k=10, filter={"kind": NodeKind.CHUNK.value})
        assert hits
        assert all(h.ref == items[0].ref for h in hits)

    async def test_delete_where_removes(self, vectors: VectorStore) -> None:
        items = make_sample_embeddings()
        await vectors.upsert(items)
        await vectors.delete_where({"kind": NodeKind.DOC_CHUNK.value})
        hits = await vectors.search(items[1].vector, k=10)
        assert items[1].ref not in {h.ref for h in hits}


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
