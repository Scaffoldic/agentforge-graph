"""SurrealDB-backed ``GraphStore`` **and** ``VectorStore`` — an opt-in *single*
server backend (ENH-010). SurrealDB is multi-model, so one server covers both
roles: ``store.graph.driver: surrealdb`` + ``store.vectors.driver: surrealdb``.

It passes the same ``GraphStoreConformance`` / ``VectorStoreConformance`` suites
as Kuzu/Neo4j/LanceDB/pgvector — the open schema (one ``ckg_node`` doc table, one
``ckg_edge`` doc table, one ``ckg_vector`` table) is the shared ``_rowmap``
flatten, with ``attrs`` a JSON string so any kind round-trips with no DDL change.

Modeling notes (validated against SurrealDB 2.x):
- ``id`` is SurrealDB's reserved record-id field, so each record is keyed by a
  hash of the symbol id (``type::record(table, sha1(id))``) and the real id lives
  in a ``key`` field — string comparisons (``WHERE key IN …``) then work cleanly.
- Edges are a **plain table** with ``src``/``dst`` string fields (not ``RELATE``
  graph edges): property-filtered, bidirectional traversal returning whole edge
  records is a simple ``SELECT … WHERE``.
- Vector search is brute-force cosine (``vector::similarity::cosine`` + ``ORDER
  BY … LIMIT``), so a scalar ``WHERE`` filter composes reliably and no index DDL
  is required.

Install: ``pip install agentforge-graph[surrealdb]``; select in ckg.yaml:

    store:
      graph:   { driver: surrealdb, config: { url: ws://host:8000/rpc } }
      vectors: { driver: surrealdb, config: { url: ws://host:8000/rpc } }

The ``surrealdb`` SDK is imported lazily in :meth:`open`, so the module imports
fine without the extra installed (the registry references it unconditionally).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from agentforge_graph.core import (
    Direction,
    Edge,
    EdgeKind,
    Embedded,
    FileSubgraph,
    GraphQuery,
    GraphStore,
    Node,
    NodeKind,
    QueryResult,
    ScoredRef,
    VectorStore,
)
from agentforge_graph.core.symbols import SymbolID

from ._rowmap import (
    acceptable_sources,
    dump_attrs,
    edge_from_row,
    edge_params,
    load_attrs,
    node_from_row,
    node_params,
)

_VEC_FILTERABLE = ("ref", "kind", "path")


def _rid(key: str) -> str:
    """A SurrealDB-safe record id for an arbitrary symbol id (the symbol id has
    spaces/`#`/parens; a hash sidesteps record-id quoting). The real id is stored
    in the ``key`` field."""
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def _node_content(p: dict[str, Any]) -> dict[str, Any]:
    """``node_params`` flatten with the symbol id moved off the reserved ``id``
    field into ``key``."""
    c = {k: v for k, v in p.items() if k != "id"}
    c["key"] = p["id"]
    return c


def _node_from_surreal(row: dict[str, Any]) -> Node:
    return node_from_row(
        {
            "id": row["key"],
            "kind": row["kind"],
            "name": row.get("name") or "",
            "span_start": row.get("span_start"),
            "span_end": row.get("span_end"),
            "attrs": row.get("attrs"),
            "prov_source": row["prov_source"],
            "prov_extractor": row.get("prov_extractor", ""),
            "prov_commit": row.get("prov_commit", ""),
            "prov_confidence": row.get("prov_confidence"),
        }
    )


def _edge_from_surreal(row: dict[str, Any]) -> Edge:
    return edge_from_row(
        {
            "kind": row["kind"],
            "attrs": row.get("attrs"),
            "prov_source": row["prov_source"],
            "prov_extractor": row.get("prov_extractor", ""),
            "prov_commit": row.get("prov_commit", ""),
            "prov_confidence": row.get("prov_confidence"),
        },
        row["src"],
        row["dst"],
    )


async def _connect(config: dict[str, Any] | None) -> Any:
    """Open a signed-in SurrealDB connection bound to a namespace + database.
    Recognised config keys: ``url`` (→ ``$CKG_SURREALDB_URL``), ``namespace``,
    ``database``, ``username``, ``password`` (→ ``$CKG_SURREALDB_PASS``)."""
    from surrealdb import AsyncSurreal

    cfg = config or {}
    url = str(cfg.get("url") or os.environ.get("CKG_SURREALDB_URL") or "ws://localhost:8000/rpc")
    namespace = str(cfg.get("namespace", "ckg"))
    database = str(cfg.get("database", "ckg"))
    user = str(cfg.get("username", "root"))
    password = str(cfg.get("password") or os.environ.get("CKG_SURREALDB_PASS") or "root")
    db: Any = AsyncSurreal(url)
    await db.connect()
    await db.signin({"username": user, "password": password})
    await db.use(namespace, database)
    # Define the (schemaless) tables up front so reads/deletes on an
    # as-yet-unwritten store are a no-op rather than a "table not found" error.
    await db.query(
        "DEFINE TABLE IF NOT EXISTS ckg_node SCHEMALESS; "
        "DEFINE TABLE IF NOT EXISTS ckg_edge SCHEMALESS; "
        "DEFINE TABLE IF NOT EXISTS ckg_vector SCHEMALESS"
    )
    return db


def _rows(result: Any) -> list[dict[str, Any]]:
    """Normalise a single-statement ``query`` result to a list of row dicts."""
    if result is None:
        return []
    return list(result) if isinstance(result, list) else [result]


class SurrealGraphStore(GraphStore):
    """Graph store backed by SurrealDB (document tables ``ckg_node``/``ckg_edge``)."""

    def __init__(self, db: Any) -> None:
        self._db = db
        self._closed = False

    @classmethod
    async def open(
        cls, path: str | Path, config: dict[str, Any] | None = None
    ) -> SurrealGraphStore:
        return cls(await _connect(config))

    async def _q(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return _rows(await self._db.query(sql, params or {}))

    # --- writes -----------------------------------------------------------

    async def upsert(self, subgraph: FileSubgraph) -> None:
        for node in subgraph.nodes:
            p = node_params(node, subgraph.path)
            await self._q(
                "UPSERT type::record('ckg_node', $r) CONTENT $c RETURN NONE",
                {"r": _rid(p["id"]), "c": _node_content(p)},
            )
        await self._q(
            "DELETE ckg_node WHERE origin_path = $p AND key NOT IN $keep",
            {"p": subgraph.path, "keep": [n.id for n in subgraph.nodes]},
        )
        await self._q("DELETE ckg_edge WHERE origin_path = $p", {"p": subgraph.path})
        for edge in subgraph.edges:
            await self._q(
                "CREATE ckg_edge CONTENT $c RETURN NONE", {"c": edge_params(edge, subgraph.path)}
            )

    async def add(self, items: list[Node | Edge]) -> None:
        for item in items:
            if isinstance(item, Node):
                p = node_params(item, "")
                await self._q(
                    "UPSERT type::record('ckg_node', $r) CONTENT $c RETURN NONE",
                    {"r": _rid(p["id"]), "c": _node_content(p)},
                )
            else:
                await self._q(
                    "CREATE ckg_edge CONTENT $c RETURN NONE", {"c": edge_params(item, "")}
                )

    async def delete_file(self, path: str) -> None:
        await self._q("DELETE ckg_edge WHERE origin_path = $p", {"p": path})
        await self._q("DELETE ckg_node WHERE origin_path = $p", {"p": path})

    async def clear_resolved(self, paths: list[str]) -> None:
        if not paths:
            return
        from agentforge_graph.core import Source

        await self._q(
            "DELETE ckg_edge WHERE origin_path IN $paths AND prov_source = $resolved",
            {"paths": paths, "resolved": Source.RESOLVED.value},
        )
        # GC external package stubs orphaned by the edge deletion (no inbound edge),
        # so an incremental re-resolve converges to a full re-index's graph.
        await self._q(
            "DELETE ckg_node WHERE kind = $pkg AND key NOT IN (SELECT VALUE dst FROM ckg_edge)",
            {"pkg": NodeKind.PACKAGE.value},
        )

    async def clear_outgoing(self, src_ids: list[str], kind: EdgeKind) -> None:
        if not src_ids:
            return
        await self._q(
            "DELETE ckg_edge WHERE src IN $ids AND kind = $kind",
            {"ids": src_ids, "kind": kind.value},
        )

    # --- reads ------------------------------------------------------------

    async def query(self, q: GraphQuery) -> QueryResult:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if q.kinds is not None:
            clauses.append("kind IN $kinds")
            params["kinds"] = [k.value for k in q.kinds]
        if q.name is not None:
            clauses.append("name = $name")
            params["name"] = q.name
        if q.path_prefix is not None:
            clauses.append("string::starts_with(sym_path, $prefix)")
            params["prefix"] = q.path_prefix
        if q.min_source is not None:
            clauses.append("prov_source IN $sources")
            params["sources"] = acceptable_sources(q.min_source)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = await self._q(f"SELECT * FROM ckg_node{where} LIMIT {q.limit + 1}", params)
        nodes = [_node_from_surreal(r) for r in rows]
        return QueryResult(nodes=nodes[: q.limit], truncated=len(nodes) > q.limit)

    async def neighbors(
        self, node_id: str, kinds: list[EdgeKind] | None = None, depth: int = 1
    ) -> list[Node]:
        kind_clause = ""
        base: dict[str, Any] = {}
        if kinds is not None:
            kind_clause = " AND kind IN $kinds"
            base["kinds"] = [k.value for k in kinds]
        visited = {node_id}
        frontier = [node_id]
        collected: list[str] = []
        for _ in range(depth):
            if not frontier:
                break
            rows = await self._q(
                f"SELECT src, dst FROM ckg_edge WHERE (src IN $f OR dst IN $f){kind_clause}",
                {**base, "f": frontier},
            )
            nxt: list[str] = []
            for r in rows:
                # the neighbour is whichever endpoint isn't already visited; the
                # frontier endpoint is visited, so it's naturally skipped.
                for end in (r["src"], r["dst"]):
                    if end not in visited:
                        visited.add(end)
                        nxt.append(end)
                        collected.append(end)
            frontier = nxt
        out: list[Node] = []
        for i in collected:
            n = await self.get(i)
            if n is not None:
                out.append(n)
        return out

    async def get(self, node_id: str) -> Node | None:
        rows = await self._q("SELECT * FROM ckg_node WHERE key = $k LIMIT 1", {"k": node_id})
        return _node_from_surreal(rows[0]) if rows else None

    async def set_attrs(self, node_id: str, attrs: dict[str, Any]) -> None:
        rows = await self._q("SELECT attrs FROM ckg_node WHERE key = $k LIMIT 1", {"k": node_id})
        if not rows:
            return  # absent node: no-op (contract)
        merged = {**load_attrs(rows[0].get("attrs")), **attrs}
        await self._q(
            "UPDATE type::record('ckg_node', $r) SET attrs = $a RETURN NONE",
            {"r": _rid(node_id), "a": dump_attrs(merged)},
        )

    async def adjacent(
        self,
        node_id: str,
        kinds: list[EdgeKind] | None = None,
        direction: Direction = "both",
    ) -> list[Edge]:
        params: dict[str, Any] = {"id": node_id}
        kind_clause = ""
        if kinds is not None:
            kind_clause = " AND kind IN $kinds"
            params["kinds"] = [k.value for k in kinds]
        if direction == "out":
            cond = "src = $id"
        elif direction == "in":
            cond = "dst = $id"
        else:
            cond = "(src = $id OR dst = $id)"
        rows = await self._q(f"SELECT * FROM ckg_edge WHERE {cond}{kind_clause}", params)
        return [_edge_from_surreal(r) for r in rows]

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._db.close()


class SurrealVectorStore(VectorStore):
    """Vector store backed by SurrealDB (``ckg_vector`` table, brute-force cosine)."""

    def __init__(self, db: Any) -> None:
        self._db = db
        self._closed = False

    @classmethod
    async def open(
        cls, path: str | Path, config: dict[str, Any] | None = None
    ) -> SurrealVectorStore:
        return cls(await _connect(config))

    async def _q(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return _rows(await self._db.query(sql, params or {}))

    async def upsert(self, items: list[Embedded]) -> None:
        for i in items:
            try:
                path = SymbolID.parse(i.ref).path
            except ValueError:
                path = ""
            await self._q(
                "UPSERT type::record('ckg_vector', $r) CONTENT $c RETURN NONE",
                {
                    "r": _rid(i.ref),
                    "c": {
                        "ref": i.ref,
                        "embedding": [float(x) for x in i.vector],
                        "kind": i.kind.value,
                        "path": path,
                        "attrs_json": json.dumps(i.attrs, sort_keys=True),
                    },
                },
            )

    async def search(
        self, vector: list[float], k: int, filter: dict[str, Any] | None = None
    ) -> list[ScoredRef]:
        params: dict[str, Any] = {"q": [float(x) for x in vector]}
        where = ""
        if filter:
            self._check_filter(filter)
            conds = []
            for col, val in filter.items():
                params[col] = val
                conds.append(f"{col} = ${col}")
            where = " WHERE " + " AND ".join(conds)
        rows = await self._q(
            "SELECT ref, attrs_json, vector::similarity::cosine(embedding, $q) AS sim "
            f"FROM ckg_vector{where} ORDER BY sim DESC LIMIT {int(k)}",
            params,
        )
        return [
            ScoredRef(
                ref=r["ref"],
                score=max(0.0, min(1.0, float(r["sim"]))),
                attrs=json.loads(r["attrs_json"]) if r.get("attrs_json") else {},
            )
            for r in rows
            if r.get("sim") is not None
        ]

    async def delete_where(self, filter: dict[str, Any]) -> None:
        self._check_filter(filter)
        params: dict[str, Any] = {}
        conds = []
        for col, val in filter.items():
            params[col] = val
            conds.append(f"{col} = ${col}")
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        await self._q(f"DELETE ckg_vector{where}", params)

    @staticmethod
    def _check_filter(filter: dict[str, Any]) -> None:
        bad = set(filter) - set(_VEC_FILTERABLE)
        if bad:
            raise ValueError(f"unfilterable column(s) {sorted(bad)}; allowed: {_VEC_FILTERABLE}")

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._db.close()
