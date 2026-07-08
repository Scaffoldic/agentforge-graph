"""Reusable query-conformance suite for ``QueryCapable`` backends (feat-015).

A backend proves it runs the read-only query surface correctly — and identically
to every other backend — by subclassing ``QueryConformance`` and providing an
async ``store`` fixture (the same pattern as feat-003's ``GraphStoreConformance``).
The suite has three mandatory parts, each a contract every query-capable backend
must pass, so the extensibility guarantees are *enforced*, not asserted in prose:

1. **Result parity** — a fixed query set returns the canonical expected rows.
   Because every backend subclasses this same suite over the same fixture, "the
   expected rows" are identical across backends by construction.
2. **Bounded execution** — a runaway query returns a partial result with the
   right ``stopped_reason`` (row / expansion cap), on every backend.
3. **Read-only** — a write cannot reach execution (the AST has no write node).

Pytest-free at import (the test package's pytest-asyncio collects the ``test_``
methods via the subclass), mirroring ``core/conformance.py``.
"""

from __future__ import annotations

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

from .capability import QueryCapable, QuerySettings, ResultTable
from .errors import ParseError
from .parser import parse_query
from .validator import validate_query

_LANG, _REPO, _PATH = "py", "sample", "src/app.py"
_PROV = Provenance.parsed("query-conformance", "c0")


def _nid(descriptor: str) -> str:
    return SymbolID.for_symbol(_LANG, _REPO, _PATH, descriptor)


def _node(descriptor: str, kind: NodeKind, name: str, span: tuple[int, int] = (1, 5)) -> Node:
    return Node(id=_nid(descriptor), kind=kind, name=name, span=span, provenance=_PROV)


def make_query_fixture() -> FileSubgraph:
    """A small graph exercising every core construct: classes implementing an
    interface, a call chain (for var-length), an orphan, and a tag."""
    file = _node("", NodeKind.FILE, "app.py")
    repo = _node(Descriptor.type("Repo"), NodeKind.CLASS, "Repo")
    cache = _node(Descriptor.type("Cache"), NodeKind.CLASS, "Cache")
    plain = _node(Descriptor.type("Plain"), NodeKind.CLASS, "Plain")
    store_if = _node(Descriptor.type("Store"), NodeKind.INTERFACE, "Store")
    empty_if = _node(Descriptor.type("Empty"), NodeKind.INTERFACE, "Empty")
    foo = _node(Descriptor.term("foo"), NodeKind.FUNCTION, "foo")
    bar = _node(Descriptor.term("bar"), NodeKind.FUNCTION, "bar")
    baz = _node(Descriptor.term("baz"), NodeKind.FUNCTION, "baz")
    qux = _node(Descriptor.term("qux"), NodeKind.FUNCTION, "qux")
    tag = _node(Descriptor.term("Repository"), NodeKind.PATTERN_TAG, "Repository")
    nodes = [file, repo, cache, plain, store_if, empty_if, foo, bar, baz, qux, tag]
    edges = [
        # CONTAINS is both an EdgeKind and the CONTAINS string operator — including
        # it proves the parser accepts a reserved word in relationship-type position.
        Edge(src=file.id, dst=repo.id, kind=EdgeKind.CONTAINS, provenance=_PROV),
        Edge(src=file.id, dst=cache.id, kind=EdgeKind.CONTAINS, provenance=_PROV),
        Edge(src=file.id, dst=plain.id, kind=EdgeKind.CONTAINS, provenance=_PROV),
        Edge(src=repo.id, dst=store_if.id, kind=EdgeKind.IMPLEMENTS, provenance=_PROV),
        Edge(src=cache.id, dst=store_if.id, kind=EdgeKind.IMPLEMENTS, provenance=_PROV),
        Edge(src=foo.id, dst=bar.id, kind=EdgeKind.CALLS, provenance=_PROV),
        Edge(src=bar.id, dst=baz.id, kind=EdgeKind.CALLS, provenance=_PROV),
        Edge(src=repo.id, dst=tag.id, kind=EdgeKind.TAGGED, provenance=_PROV),
    ]
    return FileSubgraph(path=_PATH, content_hash="h0", nodes=nodes, edges=edges)


class QueryConformance:
    """Subclass in a backend's test module; provide an async ``store`` fixture
    yielding a fresh ``QueryCapable`` graph store."""

    async def _run(
        self, store: QueryCapable, text: str, settings: QuerySettings | None = None
    ) -> ResultTable:
        ast = validate_query(parse_query(text), store.capabilities)
        return await store.run_query(ast, settings or QuerySettings())

    @staticmethod
    def _col0(rt: ResultTable) -> set[object]:
        return {row[0] for row in rt.rows}

    async def _load(self, store: QueryCapable) -> None:
        await store.upsert(make_query_fixture())  # type: ignore[attr-defined]

    # --- 1. result parity ---------------------------------------------------

    async def test_simple_projection(self, store: QueryCapable) -> None:
        await self._load(store)
        rt = await self._run(store, "MATCH (f:Function) RETURN f.name")
        assert rt.columns == ("f.name",)
        assert self._col0(rt) == {"foo", "bar", "baz", "qux"}
        assert not rt.truncated

    async def test_property_mapping(self, store: QueryCapable) -> None:
        await self._load(store)
        rt = await self._run(store, 'MATCH (c:Class {name: "Repo"}) RETURN c.path, c.start_line')
        assert rt.columns == ("c.path", "c.start_line")
        assert rt.rows == (("src/app.py", 1),)

    async def test_aggregate_and_order(self, store: QueryCapable) -> None:
        await self._load(store)
        rt = await self._run(
            store,
            "MATCH (c:Class)-[:IMPLEMENTS]->(i:Interface) "
            "RETURN i.name, count(c) AS impls ORDER BY impls DESC",
        )
        assert rt.columns == ("i.name", "impls")
        assert rt.rows == (("Store", 2),)

    async def test_pattern_exists_negation(self, store: QueryCapable) -> None:
        await self._load(store)
        # functions with no inbound CALLS: foo (caller) and qux (orphan).
        rt = await self._run(store, "MATCH (f:Function) WHERE NOT (f)<-[:CALLS]-() RETURN f.name")
        assert self._col0(rt) == {"foo", "qux"}

    async def test_variable_length_path(self, store: QueryCapable) -> None:
        await self._load(store)
        # foo -CALLS-> bar -CALLS-> baz : within 1..2 hops foo reaches bar, baz.
        rt = await self._run(
            store, 'MATCH (a:Function {name: "foo"})-[:CALLS*1..2]->(b:Function) RETURN b.name'
        )
        assert self._col0(rt) == {"bar", "baz"}

    async def test_string_predicate(self, store: QueryCapable) -> None:
        await self._load(store)
        rt = await self._run(store, 'MATCH (c:Class) WHERE c.name STARTS WITH "C" RETURN c.name')
        assert self._col0(rt) == {"Cache"}

    async def test_in_list(self, store: QueryCapable) -> None:
        await self._load(store)
        rt = await self._run(
            store, 'MATCH (f:Function) WHERE f.name IN ["foo", "qux"] RETURN f.name'
        )
        assert self._col0(rt) == {"foo", "qux"}

    async def test_tagged_classes(self, store: QueryCapable) -> None:
        await self._load(store)
        rt = await self._run(
            store,
            'MATCH (c:Class)-[:TAGGED]->(t:PatternTag) WHERE t.name = "Repository" RETURN c.name',
        )
        assert self._col0(rt) == {"Repo"}

    async def test_reserved_word_edge_kind(self, store: QueryCapable) -> None:
        # CONTAINS is a reserved word (string operator) *and* an edge kind.
        await self._load(store)
        rt = await self._run(store, "MATCH (f:File)-[:CONTAINS]->(c:Class) RETURN c.name")
        assert self._col0(rt) == {"Repo", "Cache", "Plain"}

    # --- 2. bounded execution ----------------------------------------------

    async def test_row_cap_truncates(self, store: QueryCapable) -> None:
        await self._load(store)
        rt = await self._run(store, "MATCH (f:Function) RETURN f.name", QuerySettings(max_rows=2))
        assert len(rt.rows) == 2
        assert rt.truncated and rt.stopped_reason == "row_cap"

    async def test_expansion_cap_is_a_real_backstop(self, store: QueryCapable) -> None:
        await self._load(store)
        # A hard ceiling on rows pulled, independent of the pushed LIMIT.
        rt = await self._run(
            store,
            "MATCH (f:Function) RETURN f.name",
            QuerySettings(max_rows=100, max_expansions=1),
        )
        assert len(rt.rows) == 1
        assert rt.truncated and rt.stopped_reason == "expansion_cap"

    # --- 3. read-only -------------------------------------------------------

    async def test_write_cannot_reach_execution(self, store: QueryCapable) -> None:
        await self._load(store)
        # The grammar has no write production, so a write is rejected before it
        # could ever be compiled or run — the read-only guarantee starts here.
        for text in (
            'CREATE (n:Class {name: "x"}) RETURN n.name',
            "MATCH (n:Class) DETACH DELETE n",
            "MATCH (n:Class) SET n.name = 'y' RETURN n.name",
        ):
            try:
                await self._run(store, text)
            except ParseError:
                continue
            raise AssertionError(f"write-shaped query was not rejected: {text}")
