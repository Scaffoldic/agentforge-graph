"""Kuzu-backed ``GraphStore`` — the default embedded graph adapter and the
conformance baseline for every other adapter (ADR-0006).

Design (see docs/design/design-003): an *open* schema (arbitrary kinds,
free-form ``attrs``) is mapped onto Kuzu's typed property graph via **one
generic node table + one generic edge table**, with ``kind`` as a string
column and ``attrs`` as a JSON string — so an unrecognized kind round-trips
without any DDL change (ADR-0005).

Kuzu is synchronous and a connection is not concurrency-safe, so every DB
interaction runs on a worker thread (``asyncio.to_thread``) under a single
``asyncio.Lock``; each public method's DB work is one sync function, which
keeps multi-statement writes (``upsert``) atomic on one thread.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import kuzu

from agentforge_graph.core import (
    Direction,
    Edge,
    EdgeKind,
    FileSubgraph,
    GraphQuery,
    GraphStore,
    Node,
    NodeKind,
    Provenance,
    QueryResult,
    Source,
    SymbolID,
)

# Trust ordering (PARSED is highest-trust): a node passes a ``min_source``
# floor iff its source rank is >= the floor's. Mirrors the InMemory reference.
_SOURCE_RANK = {Source.LLM: 0, Source.RESOLVED: 1, Source.MANUAL: 1, Source.PARSED: 2}

SCHEMA_VERSION = 1

_DDL = [
    """CREATE NODE TABLE CkgNode(
        id STRING, kind STRING, name STRING,
        span_start INT64, span_end INT64,
        attrs STRING, sym_path STRING,
        prov_source STRING, prov_extractor STRING,
        prov_commit STRING, prov_confidence DOUBLE,
        origin_path STRING,
        PRIMARY KEY(id))""",
    """CREATE REL TABLE CkgEdge(
        FROM CkgNode TO CkgNode,
        kind STRING, attrs STRING,
        prov_source STRING, prov_extractor STRING,
        prov_commit STRING, prov_confidence DOUBLE,
        origin_path STRING, resolved_from STRING)""",
]


def _dump_attrs(attrs: dict[str, Any]) -> str:
    return json.dumps(attrs, sort_keys=True)


def _load_attrs(s: str | None) -> dict[str, Any]:
    return json.loads(s) if s else {}


def _node_params(node: Node, origin_path: str) -> dict[str, Any]:
    span_start, span_end = node.span if node.span is not None else (None, None)
    p = node.provenance
    return {
        "id": node.id,
        "kind": node.kind.value,
        "name": node.name,
        "span_start": span_start,
        "span_end": span_end,
        "attrs": _dump_attrs(node.attrs),
        "sym_path": SymbolID.parse(node.id).path,
        "prov_source": p.source.value,
        "prov_extractor": p.extractor,
        "prov_commit": p.commit,
        "prov_confidence": p.confidence,
        "origin_path": origin_path,
    }


def _edge_params(edge: Edge, origin_path: str) -> dict[str, Any]:
    p = edge.provenance
    return {
        "src": edge.src,
        "dst": edge.dst,
        "kind": edge.kind.value,
        "attrs": _dump_attrs(edge.attrs),
        "prov_source": p.source.value,
        "prov_extractor": p.extractor,
        "prov_commit": p.commit,
        "prov_confidence": p.confidence,
        # An edge that carries its own owner file (resolver edges, feat-004)
        # wins; otherwise the caller's stamp (the upserted file's path).
        "origin_path": edge.origin_path or origin_path,
        "resolved_from": "",
    }


def _prov_from_row(d: dict[str, Any]) -> Provenance:
    # The validating constructor — a corrupt row fails loudly, not silently.
    return Provenance(
        source=Source(d["prov_source"]),
        extractor=d["prov_extractor"],
        commit=d["prov_commit"],
        confidence=d["prov_confidence"],
    )


def _edge_from_rel(rel: dict[str, Any], src: str, dst: str) -> Edge:
    return Edge(
        src=src,
        dst=dst,
        kind=EdgeKind(rel["kind"]),
        attrs=_load_attrs(rel["attrs"]),
        provenance=_prov_from_row(rel),
    )


def _node_from_row(d: dict[str, Any]) -> Node:
    span = (d["span_start"], d["span_end"]) if d["span_start"] is not None else None
    return Node(
        id=d["id"],
        kind=NodeKind(d["kind"]),
        name=d["name"],
        span=span,
        attrs=_load_attrs(d["attrs"]),
        provenance=_prov_from_row(d),
    )


def _rows(result: Any) -> list[Any]:
    # kuzu's execute() returns QueryResult | list[QueryResult] (multi-statement)
    # and get_next() a list|dict row; we always issue single statements.
    out: list[Any] = []
    while result.has_next():
        out.append(result.get_next())
    return out


def _acceptable_sources(floor: Source) -> list[str]:
    threshold = _SOURCE_RANK[floor]
    return [s.value for s, rank in _SOURCE_RANK.items() if rank >= threshold]


class KuzuGraphStore(GraphStore):
    """Embedded graph store backed by a Kuzu database directory."""

    def __init__(self, db: kuzu.Database, conn: kuzu.Connection, path: Path) -> None:
        self._db = db
        self._conn = conn
        self._path = path
        self._lock = asyncio.Lock()
        self._closed = False

    @classmethod
    async def open(cls, path: str | Path) -> KuzuGraphStore:
        """Open (creating if needed) a Kuzu database at ``path`` and ensure
        the schema exists. ``path`` is the graph DB directory/file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        db, conn = await asyncio.to_thread(cls._connect, p)
        return cls(db, conn, p)

    @staticmethod
    def _connect(p: Path) -> tuple[kuzu.Database, kuzu.Connection]:
        db = kuzu.Database(str(p))
        conn = kuzu.Connection(db)
        for ddl in _DDL:
            try:
                conn.execute(ddl)
            except RuntimeError as exc:  # table already exists on reopen
                if "already exists" not in str(exc):
                    raise
        return db, conn

    # --- writes -----------------------------------------------------------

    async def upsert(self, subgraph: FileSubgraph) -> None:
        async with self._lock:
            await asyncio.to_thread(self._upsert_sync, subgraph)

    def _upsert_sync(self, sg: FileSubgraph) -> None:
        path = sg.path
        new_ids = [n.id for n in sg.nodes]
        self._conn.execute("BEGIN TRANSACTION")
        try:
            for node in sg.nodes:
                self._merge_node(node, origin_path=path)
            # drop file-owned nodes that vanished from the new subgraph
            self._conn.execute(
                "MATCH (n:CkgNode) WHERE n.origin_path = $p AND NOT n.id IN $keep DETACH DELETE n",
                {"p": path, "keep": new_ids},
            )
            # replace this file's edges
            self._conn.execute(
                "MATCH ()-[e:CkgEdge]->() WHERE e.origin_path = $p DELETE e", {"p": path}
            )
            for edge in sg.edges:
                self._insert_edge(edge, origin_path=path)
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    async def add(self, items: list[Node | Edge]) -> None:
        async with self._lock:
            await asyncio.to_thread(self._add_sync, items)

    def _add_sync(self, items: list[Node | Edge]) -> None:
        self._conn.execute("BEGIN TRANSACTION")
        try:
            for item in items:
                if isinstance(item, Node):
                    self._merge_node(item, origin_path="")
                else:
                    self._insert_edge(item, origin_path="")
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def _merge_node(self, node: Node, origin_path: str) -> None:
        self._conn.execute(
            "MERGE (n:CkgNode {id: $id}) SET "
            "n.kind = $kind, n.name = $name, "
            "n.span_start = $span_start, n.span_end = $span_end, "
            "n.attrs = $attrs, n.sym_path = $sym_path, "
            "n.prov_source = $prov_source, n.prov_extractor = $prov_extractor, "
            "n.prov_commit = $prov_commit, n.prov_confidence = $prov_confidence, "
            "n.origin_path = $origin_path",
            _node_params(node, origin_path),
        )

    def _insert_edge(self, edge: Edge, origin_path: str) -> None:
        # Endpoints must exist; an edge to an absent node is dropped silently
        # by the MATCH (resolved cross-file edges may outrun their target —
        # they reconnect when the target file is indexed).
        self._conn.execute(
            "MATCH (a:CkgNode {id: $src}), (b:CkgNode {id: $dst}) "
            "CREATE (a)-[e:CkgEdge {kind: $kind}]->(b) SET "
            "e.attrs = $attrs, e.prov_source = $prov_source, "
            "e.prov_extractor = $prov_extractor, e.prov_commit = $prov_commit, "
            "e.prov_confidence = $prov_confidence, e.origin_path = $origin_path, "
            "e.resolved_from = $resolved_from",
            _edge_params(edge, origin_path),
        )

    async def delete_file(self, path: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._delete_file_sync, path)

    def _delete_file_sync(self, path: str) -> None:
        self._conn.execute("BEGIN TRANSACTION")
        try:
            self._conn.execute(
                "MATCH ()-[e:CkgEdge]->() WHERE e.origin_path = $p DELETE e", {"p": path}
            )
            self._conn.execute(
                "MATCH (n:CkgNode) WHERE n.origin_path = $p DETACH DELETE n", {"p": path}
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    async def clear_resolved(self, paths: list[str]) -> None:
        async with self._lock:
            await asyncio.to_thread(self._clear_resolved_sync, paths)

    def _clear_resolved_sync(self, paths: list[str]) -> None:
        if not paths:
            return
        self._conn.execute("BEGIN TRANSACTION")
        try:
            self._conn.execute(
                "MATCH ()-[e:CkgEdge]->() "
                "WHERE e.origin_path IN $paths AND e.prov_source = $resolved DELETE e",
                {"paths": paths, "resolved": Source.RESOLVED.value},
            )
            # GC external package stubs orphaned by the edge deletion, so the
            # incremental graph matches a full re-index (no dangling sinks).
            self._conn.execute(
                "MATCH (p:CkgNode) WHERE p.kind = $pkg "
                "OPTIONAL MATCH ()-[e:CkgEdge]->(p) "
                "WITH p, count(e) AS c WHERE c = 0 DETACH DELETE p",
                {"pkg": NodeKind.PACKAGE.value},
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    # --- reads ------------------------------------------------------------

    async def query(self, q: GraphQuery) -> QueryResult:
        async with self._lock:
            return await asyncio.to_thread(self._query_sync, q)

    def _query_sync(self, q: GraphQuery) -> QueryResult:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if q.kinds is not None:
            clauses.append("n.kind IN $kinds")
            params["kinds"] = [k.value for k in q.kinds]
        if q.name is not None:
            clauses.append("n.name = $name")
            params["name"] = q.name
        if q.path_prefix is not None:
            clauses.append("n.sym_path STARTS WITH $prefix")
            params["prefix"] = q.path_prefix
        if q.min_source is not None:
            clauses.append("n.prov_source IN $sources")
            params["sources"] = _acceptable_sources(q.min_source)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params["lim"] = q.limit + 1  # fetch one extra to detect truncation
        result = self._conn.execute(f"MATCH (n:CkgNode){where} RETURN n LIMIT $lim", params)
        nodes = [_node_from_row(row[0]) for row in _rows(result)]
        truncated = len(nodes) > q.limit
        return QueryResult(nodes=nodes[: q.limit], truncated=truncated)

    async def neighbors(
        self,
        node_id: str,
        kinds: list[EdgeKind] | None = None,
        depth: int = 1,
    ) -> list[Node]:
        async with self._lock:
            return await asyncio.to_thread(self._neighbors_sync, node_id, kinds, depth)

    def _neighbors_sync(self, node_id: str, kinds: list[EdgeKind] | None, depth: int) -> list[Node]:
        # Iterative 1-hop BFS (undirected, kind-filtered), mirroring the
        # InMemory reference; depth is small (<= serve.max_depth).
        kind_values = [k.value for k in kinds] if kinds is not None else None
        visited = {node_id}
        frontier = [node_id]
        collected: list[str] = []
        for _ in range(depth):
            if not frontier:
                break
            params: dict[str, Any] = {"frontier": frontier}
            kind_clause = ""
            if kind_values is not None:
                kind_clause = " AND e.kind IN $kinds"
                params["kinds"] = kind_values
            result = self._conn.execute(
                "MATCH (a:CkgNode)-[e:CkgEdge]-(b:CkgNode) "
                f"WHERE a.id IN $frontier{kind_clause} RETURN DISTINCT b.id",
                params,
            )
            nxt: list[str] = []
            for row in _rows(result):
                nid = row[0]
                if nid not in visited:
                    visited.add(nid)
                    nxt.append(nid)
                    collected.append(nid)
            frontier = nxt
        return [n for n in (self._get_sync(i) for i in collected) if n is not None]

    async def get(self, node_id: str) -> Node | None:
        async with self._lock:
            return await asyncio.to_thread(self._get_sync, node_id)

    def _get_sync(self, node_id: str) -> Node | None:
        result = self._conn.execute("MATCH (n:CkgNode {id: $id}) RETURN n", {"id": node_id})
        rows = _rows(result)
        return _node_from_row(rows[0][0]) if rows else None

    async def adjacent(
        self,
        node_id: str,
        kinds: list[EdgeKind] | None = None,
        direction: Direction = "both",
    ) -> list[Edge]:
        async with self._lock:
            return await asyncio.to_thread(self._adjacent_sync, node_id, kinds, direction)

    def _adjacent_sync(
        self, node_id: str, kinds: list[EdgeKind] | None, direction: Direction
    ) -> list[Edge]:
        params: dict[str, Any] = {"id": node_id}
        where = ""
        if kinds is not None:
            where = " WHERE e.kind IN $kinds"
            params["kinds"] = [k.value for k in kinds]
        edges: list[Edge] = []
        if direction in ("out", "both"):
            res = self._conn.execute(
                f"MATCH (a:CkgNode {{id: $id}})-[e:CkgEdge]->(b:CkgNode){where} RETURN e, b.id",
                params,
            )
            edges += [_edge_from_rel(row[0], node_id, row[1]) for row in _rows(res)]
        if direction in ("in", "both"):
            res = self._conn.execute(
                f"MATCH (a:CkgNode {{id: $id}})<-[e:CkgEdge]-(b:CkgNode){where} RETURN e, b.id",
                params,
            )
            edges += [_edge_from_rel(row[0], row[1], node_id) for row in _rows(res)]
        return edges

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            await asyncio.to_thread(self._conn.close)
