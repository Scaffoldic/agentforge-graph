"""Neo4j-backed ``GraphStore`` — an opt-in *server* graph adapter (ENH-004).

For teams that want a shared, server-backed graph (multiple devs/CI hit one
store) or to reuse existing Neo4j infra. Neo4j speaks Cypher, like the embedded
Kuzu default, so this is a close port: the same open schema (one ``:CkgNode``
label + one ``:CkgEdge`` relationship type, ``kind`` a property, ``attrs`` a JSON
string) mapped via the shared ``_rowmap`` helpers, and it passes the same
``GraphStoreConformance`` suite Kuzu does.

Install: ``pip install agentforge-graph[neo4j]``; select in ckg.yaml:

    store:
      graph: { driver: neo4j, config: { uri: bolt://host:7687, user: neo4j } }

The ``neo4j`` driver is imported lazily in :meth:`open`, so the module imports
fine without the extra installed (the registry can reference it unconditionally).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentforge_graph.core import (
    Direction,
    Edge,
    EdgeKind,
    FileSubgraph,
    GraphQuery,
    GraphStore,
    Node,
    NodeKind,
    QueryResult,
)

from ._rowmap import (
    acceptable_sources,
    edge_from_row,
    edge_params,
    node_from_row,
    node_params,
)

if TYPE_CHECKING:
    from neo4j import AsyncDriver, AsyncManagedTransaction

# id uniqueness makes MERGE-by-id idempotent and fast (the conformance baseline).
_CONSTRAINT = "CREATE CONSTRAINT ckg_node_id IF NOT EXISTS FOR (n:CkgNode) REQUIRE n.id IS UNIQUE"
_MERGE_NODE = (
    "MERGE (n:CkgNode {id: $id}) SET "
    "n.kind = $kind, n.name = $name, "
    "n.span_start = $span_start, n.span_end = $span_end, "
    "n.attrs = $attrs, n.sym_path = $sym_path, "
    "n.prov_source = $prov_source, n.prov_extractor = $prov_extractor, "
    "n.prov_commit = $prov_commit, n.prov_confidence = $prov_confidence, "
    "n.origin_path = $origin_path"
)
_INSERT_EDGE = (
    "MATCH (a:CkgNode {id: $src}), (b:CkgNode {id: $dst}) "
    "CREATE (a)-[e:CkgEdge {kind: $kind}]->(b) SET "
    "e.attrs = $attrs, e.prov_source = $prov_source, "
    "e.prov_extractor = $prov_extractor, e.prov_commit = $prov_commit, "
    "e.prov_confidence = $prov_confidence, e.origin_path = $origin_path, "
    "e.resolved_from = $resolved_from"
)


class Neo4jGraphStore(GraphStore):
    """Server graph store backed by Neo4j (Bolt)."""

    def __init__(self, driver: AsyncDriver, database: str) -> None:
        self._driver = driver
        self._database = database
        self._closed = False

    @classmethod
    async def open(cls, path: str | Path, config: dict[str, Any] | None = None) -> Neo4jGraphStore:
        """Connect to Neo4j from the ``store.graph.config`` block. ``path`` (the
        embedded ``.ckg/`` location) is ignored. Recognised config keys: ``uri``,
        ``user``, ``password`` (falls back to ``$CKG_NEO4J_PASSWORD``), ``database``.
        Raises at open (not mid-index) if the server is unreachable."""
        from neo4j import AsyncGraphDatabase

        cfg = config or {}
        uri = str(cfg.get("uri") or os.environ.get("CKG_NEO4J_URI") or "bolt://localhost:7687")
        user = str(cfg.get("user", "neo4j"))
        password = str(cfg.get("password") or os.environ.get("CKG_NEO4J_PASSWORD") or "")
        database = str(cfg.get("database", "neo4j"))
        driver: AsyncDriver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        await driver.verify_connectivity()
        async with driver.session(database=database) as session:
            await session.run(_CONSTRAINT)
        return cls(driver, database)

    # --- writes -----------------------------------------------------------

    async def upsert(self, subgraph: FileSubgraph) -> None:
        async with self._driver.session(database=self._database) as session:
            await session.execute_write(self._upsert_tx, subgraph)

    @staticmethod
    async def _upsert_tx(tx: AsyncManagedTransaction, sg: FileSubgraph) -> None:
        for node in sg.nodes:
            await tx.run(_MERGE_NODE, node_params(node, sg.path))
        await tx.run(
            "MATCH (n:CkgNode) WHERE n.origin_path = $p AND NOT n.id IN $keep DETACH DELETE n",
            p=sg.path,
            keep=[n.id for n in sg.nodes],
        )
        await tx.run("MATCH ()-[e:CkgEdge]->() WHERE e.origin_path = $p DELETE e", p=sg.path)
        for edge in sg.edges:
            await tx.run(_INSERT_EDGE, edge_params(edge, sg.path))

    async def add(self, items: list[Node | Edge]) -> None:
        async with self._driver.session(database=self._database) as session:
            await session.execute_write(self._add_tx, items)

    @staticmethod
    async def _add_tx(tx: AsyncManagedTransaction, items: list[Node | Edge]) -> None:
        for item in items:
            if isinstance(item, Node):
                await tx.run(_MERGE_NODE, node_params(item, ""))
            else:
                await tx.run(_INSERT_EDGE, edge_params(item, ""))

    async def delete_file(self, path: str) -> None:
        async with self._driver.session(database=self._database) as session:
            await session.execute_write(self._delete_file_tx, path)

    @staticmethod
    async def _delete_file_tx(tx: AsyncManagedTransaction, path: str) -> None:
        await tx.run("MATCH ()-[e:CkgEdge]->() WHERE e.origin_path = $p DELETE e", p=path)
        await tx.run("MATCH (n:CkgNode) WHERE n.origin_path = $p DETACH DELETE n", p=path)

    async def clear_resolved(self, paths: list[str]) -> None:
        if not paths:
            return
        async with self._driver.session(database=self._database) as session:
            await session.execute_write(self._clear_resolved_tx, paths)

    @staticmethod
    async def _clear_resolved_tx(tx: AsyncManagedTransaction, paths: list[str]) -> None:
        from agentforge_graph.core import Source

        await tx.run(
            "MATCH ()-[e:CkgEdge]->() "
            "WHERE e.origin_path IN $paths AND e.prov_source = $resolved DELETE e",
            paths=paths,
            resolved=Source.RESOLVED.value,
        )
        # GC external package stubs orphaned by the edge deletion, so the
        # incremental graph matches a full re-index (no dangling sinks).
        await tx.run(
            "MATCH (p:CkgNode) WHERE p.kind = $pkg AND NOT ()-[:CkgEdge]->(p) DETACH DELETE p",
            pkg=NodeKind.PACKAGE.value,
        )

    async def clear_outgoing(self, src_ids: list[str], kind: EdgeKind) -> None:
        if not src_ids:
            return
        async with self._driver.session(database=self._database) as session:
            await session.run(
                "MATCH (a:CkgNode)-[e:CkgEdge]->() WHERE a.id IN $ids AND e.kind = $kind DELETE e",
                ids=src_ids,
                kind=kind.value,
            )

    # --- reads ------------------------------------------------------------

    async def query(self, q: GraphQuery) -> QueryResult:
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
            params["sources"] = acceptable_sources(q.min_source)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params["lim"] = q.limit + 1  # one extra to detect truncation
        rows = await self._read(f"MATCH (n:CkgNode){where} RETURN n LIMIT $lim", params)
        nodes = [node_from_row(dict(r["n"])) for r in rows]
        return QueryResult(nodes=nodes[: q.limit], truncated=len(nodes) > q.limit)

    async def neighbors(
        self, node_id: str, kinds: list[EdgeKind] | None = None, depth: int = 1
    ) -> list[Node]:
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
            rows = await self._read(
                "MATCH (a:CkgNode)-[e:CkgEdge]-(b:CkgNode) "
                f"WHERE a.id IN $frontier{kind_clause} RETURN DISTINCT b.id AS id",
                params,
            )
            nxt: list[str] = []
            for r in rows:
                nid = r["id"]
                if nid not in visited:
                    visited.add(nid)
                    nxt.append(nid)
                    collected.append(nid)
            frontier = nxt
        out: list[Node] = []
        for i in collected:
            n = await self.get(i)
            if n is not None:
                out.append(n)
        return out

    async def get(self, node_id: str) -> Node | None:
        rows = await self._read("MATCH (n:CkgNode {id: $id}) RETURN n", {"id": node_id})
        return node_from_row(dict(rows[0]["n"])) if rows else None

    async def adjacent(
        self,
        node_id: str,
        kinds: list[EdgeKind] | None = None,
        direction: Direction = "both",
    ) -> list[Edge]:
        params: dict[str, Any] = {"id": node_id}
        where = ""
        if kinds is not None:
            where = " WHERE e.kind IN $kinds"
            params["kinds"] = [k.value for k in kinds]
        edges: list[Edge] = []
        if direction in ("out", "both"):
            rows = await self._read(
                f"MATCH (a:CkgNode {{id: $id}})-[e:CkgEdge]->(b:CkgNode){where} "
                "RETURN e, b.id AS oid",
                params,
            )
            edges += [edge_from_row(dict(r["e"]), node_id, r["oid"]) for r in rows]
        if direction in ("in", "both"):
            rows = await self._read(
                f"MATCH (a:CkgNode {{id: $id}})<-[e:CkgEdge]-(b:CkgNode){where} "
                "RETURN e, b.id AS oid",
                params,
            )
            edges += [edge_from_row(dict(r["e"]), r["oid"], node_id) for r in rows]
        return edges

    async def _read(self, cypher: str, params: dict[str, Any]) -> list[Any]:
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, params)
            return [r async for r in result]

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._driver.close()
