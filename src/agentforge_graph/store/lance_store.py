"""LanceDB-backed ``VectorStore`` — the default embedded vector adapter
(ADR-0006). feat-005 produces the ``Embedded`` items; feat-006 searches
them and joins the hits back into the graph via ``Store.expand``.

LanceDB ships a native async client, so this adapter is async all the way
down (no thread-wrapping, unlike the sync Kuzu adapter). One ``vectors``
table is created lazily on first ``upsert`` with the vector dimension fixed
from the first batch. The ``filter`` contract targets first-class columns
(``ref``, ``kind``, ``path``) — the portable subset every vector backend can
honour; ``path`` is derived from the ref's SymbolID, mirroring the graph
adapter's ``sym_path``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa

from agentforge_graph.core import Embedded, ScoredRef, VectorStore
from agentforge_graph.core.symbols import SymbolID

_TABLE = "vectors"
_FILTERABLE = ("ref", "kind", "path")


def _sym_path(ref: str) -> str:
    try:
        return SymbolID.parse(ref).path
    except ValueError:
        return ""


def _sql_str(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _where(filter: dict[str, Any]) -> str:
    bad = set(filter) - set(_FILTERABLE)
    if bad:
        raise ValueError(f"unfilterable column(s) {sorted(bad)}; allowed: {_FILTERABLE}")
    return " AND ".join(f"{col} = {_sql_str(val)}" for col, val in filter.items())


def _row(item: Embedded) -> dict[str, Any]:
    return {
        "ref": item.ref,
        "vector": [float(x) for x in item.vector],
        "kind": item.kind.value,
        "path": _sym_path(item.ref),
        "attrs_json": json.dumps(item.attrs, sort_keys=True),
    }


def _schema(dim: int) -> pa.Schema:
    return pa.schema(
        [
            pa.field("ref", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
            pa.field("kind", pa.string()),
            pa.field("path", pa.string()),
            pa.field("attrs_json", pa.string()),
        ]
    )


class LanceVectorStore(VectorStore):
    """Embedded vector store backed by a LanceDB database directory."""

    def __init__(self, db: Any, path: Path) -> None:
        self._db = db
        self._path = path
        self._tbl: Any = None
        self._closed = False

    @classmethod
    async def open(cls, path: str | Path) -> LanceVectorStore:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        db = await lancedb.connect_async(str(p))
        return cls(db, p)

    async def _table(self) -> Any:
        if self._tbl is None and _TABLE in await self._db.list_tables():
            self._tbl = await self._db.open_table(_TABLE)
        return self._tbl

    async def upsert(self, items: list[Embedded]) -> None:
        if not items:
            return
        tbl = await self._table()
        if tbl is None:
            tbl = await self._db.create_table(_TABLE, schema=_schema(len(items[0].vector)))
            self._tbl = tbl
        refs = ", ".join(_sql_str(i.ref) for i in items)
        await tbl.delete(f"ref IN ({refs})")  # delete-then-add = upsert by ref
        await tbl.add([_row(i) for i in items])

    async def search(
        self,
        vector: list[float],
        k: int,
        filter: dict[str, Any] | None = None,
    ) -> list[ScoredRef]:
        tbl = await self._table()
        if tbl is None:
            return []
        query = tbl.vector_search(vector).limit(k)
        if filter:
            query = query.where(_where(filter))
        rows = await query.to_list()
        # LanceDB returns _distance (smaller = closer); ScoredRef score is
        # higher = closer, so negate.
        return [
            ScoredRef(
                ref=r["ref"],
                score=-float(r["_distance"]),
                attrs=json.loads(r["attrs_json"]) if r.get("attrs_json") else {},
            )
            for r in rows
        ]

    async def delete_where(self, filter: dict[str, Any]) -> None:
        tbl = await self._table()
        if tbl is None:
            return
        await tbl.delete(_where(filter))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._db.close()  # LanceDB's async connection close() is synchronous
