"""Exercises the core conformance suites against an in-memory reference
implementation, proving the suites themselves are runnable. feat-003
adapters and feat-002 packs reuse the same base classes.
"""

from __future__ import annotations

import contextlib

import pytest

from agentforge_graph.core import (
    Edge,
    EdgeKind,
    Extractor,
    FileSubgraph,
    GraphQuery,
    GraphStore,
    Node,
    NodeKind,
    Provenance,
    QueryResult,
    Source,
    SourceFile,
    SymbolID,
)
from agentforge_graph.core.conformance import (
    ExtractorConformance,
    GraphStoreConformance,
)
from agentforge_graph.core.symbols import ParsedSymbol

_SOURCE_RANK = {Source.LLM: 0, Source.RESOLVED: 1, Source.MANUAL: 1, Source.PARSED: 2}


class InMemoryGraphStore(GraphStore):
    """Reference, dependency-free GraphStore for tests and conformance."""

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []
        self._path_nodes: dict[str, set[str]] = {}
        self._path_edges: dict[str, list[Edge]] = {}

    async def upsert(self, subgraph: FileSubgraph) -> None:
        await self.delete_file(subgraph.path)
        for n in subgraph.nodes:
            self._nodes[n.id] = n
        self._path_nodes[subgraph.path] = {n.id for n in subgraph.nodes}
        self._edges.extend(subgraph.edges)
        self._path_edges[subgraph.path] = list(subgraph.edges)

    async def add(self, items: list[Node | Edge]) -> None:
        for item in items:
            if isinstance(item, Node):
                self._nodes[item.id] = item
            else:
                self._edges.append(item)

    async def delete_file(self, path: str) -> None:
        for nid in self._path_nodes.pop(path, set()):
            self._nodes.pop(nid, None)
        for edge in self._path_edges.pop(path, []):
            with contextlib.suppress(ValueError):
                self._edges.remove(edge)

    async def clear_resolved(self, paths: list[str]) -> None:
        pathset = set(paths)
        self._edges = [
            e
            for e in self._edges
            if not (e.origin_path in pathset and e.provenance.source is Source.RESOLVED)
        ]
        inbound = {e.dst for e in self._edges}
        for nid, n in list(self._nodes.items()):
            if n.kind is NodeKind.PACKAGE and nid not in inbound:
                self._nodes.pop(nid, None)

    async def clear_outgoing(self, src_ids: list[str], kind: EdgeKind) -> None:
        srcs = set(src_ids)
        self._edges = [e for e in self._edges if not (e.src in srcs and e.kind is kind)]

    async def query(self, q: GraphQuery) -> QueryResult:
        matched: list[Node] = []
        for n in self._nodes.values():
            if q.kinds is not None and n.kind not in q.kinds:
                continue
            if q.name is not None and n.name != q.name:
                continue
            if q.path_prefix is not None:
                path = SymbolID.parse(n.id).path
                if not path.startswith(q.path_prefix):
                    continue
            if (
                q.min_source is not None
                and _SOURCE_RANK[n.provenance.source] < _SOURCE_RANK[q.min_source]
            ):
                continue
            matched.append(n)
        return QueryResult(nodes=matched[: q.limit], truncated=len(matched) > q.limit)

    async def neighbors(
        self,
        node_id: str,
        kinds: list[EdgeKind] | None = None,
        depth: int = 1,
    ) -> list[Node]:
        kindset = set(kinds) if kinds is not None else None
        visited = {node_id}
        frontier = {node_id}
        collected: list[str] = []
        for _ in range(depth):
            nxt: set[str] = set()
            for e in self._edges:
                if kindset is not None and e.kind not in kindset:
                    continue
                for a, b in ((e.src, e.dst), (e.dst, e.src)):
                    if a in frontier and b not in visited:
                        visited.add(b)
                        nxt.add(b)
                        collected.append(b)
            frontier = nxt
            if not frontier:
                break
        return [self._nodes[i] for i in collected if i in self._nodes]

    async def get(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    async def set_attrs(self, node_id: str, attrs: dict) -> None:
        node = self._nodes.get(node_id)
        if node is None:  # absent node: no-op (contract)
            return
        # merge attrs only; file ownership (_path_nodes) is left intact
        self._nodes[node_id] = node.model_copy(update={"attrs": {**node.attrs, **attrs}})

    async def adjacent(
        self,
        node_id: str,
        kinds: list[EdgeKind] | None = None,
        direction: str = "both",
    ) -> list[Edge]:
        kindset = set(kinds) if kinds is not None else None
        out: list[Edge] = []
        for e in self._edges:
            if kindset is not None and e.kind not in kindset:
                continue
            if (
                direction in ("out", "both")
                and e.src == node_id
                or direction in ("in", "both")
                and e.dst == node_id
            ):
                out.append(e)
        return out

    async def close(self) -> None:
        return None


class FakeExtractor(Extractor):
    name = "fake"

    def extract(self, file: SourceFile) -> FileSubgraph:
        sid = SymbolID.for_symbol(file.language, "repo", file.path, "")
        node = Node(
            id=sid,
            kind=NodeKind.FILE,
            name=file.path,
            provenance=Provenance.parsed("fake"),
        )
        return FileSubgraph(path=file.path, content_hash=file.content_hash, nodes=[node], edges=[])


class TestInMemoryGraphStore(GraphStoreConformance):
    @pytest.fixture
    def store(self) -> InMemoryGraphStore:
        return InMemoryGraphStore()


class TestFakeExtractor(ExtractorConformance):
    @pytest.fixture
    def extractor(self) -> FakeExtractor:
        return FakeExtractor()

    @pytest.fixture
    def sample_file(self) -> SourceFile:
        return SourceFile(path="a.py", text="x = 1", language="py", content_hash="h")


async def test_query_respects_limit_and_truncation() -> None:
    store = InMemoryGraphStore()
    prov = Provenance.parsed("t")
    for i in range(5):
        sid = SymbolID.for_symbol("py", "repo", f"f{i}.py", "")
        await store.add([Node(id=sid, kind=NodeKind.FILE, name=f"f{i}", provenance=prov)])
    res = await store.query(GraphQuery(limit=3))
    assert len(res.nodes) == 3
    assert res.truncated is True


def test_inmemory_id_parses() -> None:
    sid = SymbolID.for_symbol("py", "repo", "f.py", "")
    assert isinstance(SymbolID.parse(sid), ParsedSymbol)
