"""Postgres + pgvector ``VectorStore`` — an opt-in *server* vector adapter
(ENH-004), so teams reuse an existing Postgres instead of the embedded LanceDB.

Mirrors the LanceDB adapter's shape: one ``vectors`` table created lazily on the
first ``upsert`` (dimension fixed from the first batch), the same first-class
filter columns (``ref``, ``kind``, ``path``), and a cosine similarity in [0, 1]
(higher = closer, BUG-002). Passes the same ``VectorStoreConformance`` suite.

Install: ``pip install agentforge-graph[pgvector]``; select in ckg.yaml:

    store:
      vectors: { driver: pgvector, config: { dsn: postgresql://user@host/db } }

``asyncpg``/``pgvector`` are imported lazily in :meth:`open`, so the module
imports fine without the extra (the registry can reference it unconditionally).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentforge_graph.core import Embedded, ScoredRef, VectorStore
from agentforge_graph.core.symbols import SymbolID

if TYPE_CHECKING:
    from asyncpg import Pool

_TABLE = "ckg_vectors"
_FILTERABLE = ("ref", "kind", "path")


def _sym_path(ref: str) -> str:
    try:
        return SymbolID.parse(ref).path
    except ValueError:
        return ""


def _check_filter(filter: dict[str, Any]) -> None:
    bad = set(filter) - set(_FILTERABLE)
    if bad:
        raise ValueError(f"unfilterable column(s) {sorted(bad)}; allowed: {_FILTERABLE}")


class PgVectorStore(VectorStore):
    """Server vector store backed by Postgres + the pgvector extension."""

    def __init__(self, pool: Pool, dim: int | None) -> None:
        self._pool = pool
        self._dim = dim  # None until the table exists (created on first upsert)
        self._closed = False

    @classmethod
    async def open(cls, path: str | Path, config: dict[str, Any] | None = None) -> PgVectorStore:
        """Connect to Postgres from the ``store.vectors.config`` block. ``path``
        (the embedded ``.ckg/`` location) is ignored. Recognised config keys:
        ``dsn`` (falls back to ``$CKG_PGVECTOR_DSN``). Ensures the ``vector``
        extension exists and registers the type on every pooled connection."""
        import asyncpg
        from pgvector.asyncpg import register_vector

        cfg = config or {}
        dsn = str(cfg.get("dsn") or os.environ.get("CKG_PGVECTOR_DSN") or "")

        async def _init(conn: Any) -> None:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await register_vector(conn)

        pool = await asyncpg.create_pool(dsn, init=_init, min_size=1, max_size=4)
        # discover the dimension if the table already exists (reopen).
        dim: int | None = None
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT a.atttypmod AS dim FROM pg_attribute a "
                "JOIN pg_class c ON a.attrelid = c.oid "
                "WHERE c.relname = $1 AND a.attname = 'embedding'",
                _TABLE,
            )
            if row is not None and row["dim"] is not None and row["dim"] > 0:
                dim = int(row["dim"])
        return cls(pool, dim)

    async def _ensure_table(self, dim: int) -> None:
        if self._dim is not None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
                "ref TEXT PRIMARY KEY, "
                f"embedding vector({dim}), "
                "kind TEXT, path TEXT, attrs_json TEXT)"
            )
        self._dim = dim

    async def upsert(self, items: list[Embedded]) -> None:
        if not items:
            return
        await self._ensure_table(len(items[0].vector))
        rows = [
            (
                i.ref,
                [float(x) for x in i.vector],
                i.kind.value,
                _sym_path(i.ref),
                json.dumps(i.attrs, sort_keys=True),
            )
            for i in items
        ]
        async with self._pool.acquire() as conn:
            await conn.executemany(
                f"INSERT INTO {_TABLE} (ref, embedding, kind, path, attrs_json) "
                "VALUES ($1, $2, $3, $4, $5) "
                "ON CONFLICT (ref) DO UPDATE SET "
                "embedding = EXCLUDED.embedding, kind = EXCLUDED.kind, "
                "path = EXCLUDED.path, attrs_json = EXCLUDED.attrs_json",
                rows,
            )

    async def search(
        self, vector: list[float], k: int, filter: dict[str, Any] | None = None
    ) -> list[ScoredRef]:
        if self._dim is None:
            return []
        params: list[Any] = [[float(x) for x in vector]]
        where = ""
        if filter:
            _check_filter(filter)
            conds = []
            for col, val in filter.items():
                params.append(val)
                conds.append(f"{col} = ${len(params)}")
            where = " WHERE " + " AND ".join(conds)
        params.append(k)
        # `<=>` is cosine distance in [0, 2]; expose a similarity in [0, 1].
        sql = (
            f"SELECT ref, attrs_json, 1 - (embedding <=> $1) AS sim "
            f"FROM {_TABLE}{where} ORDER BY embedding <=> $1 LIMIT ${len(params)}"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [
            ScoredRef(
                ref=r["ref"],
                score=max(0.0, min(1.0, float(r["sim"]))),
                attrs=json.loads(r["attrs_json"]) if r["attrs_json"] else {},
            )
            for r in rows
        ]

    async def delete_where(self, filter: dict[str, Any]) -> None:
        if self._dim is None:
            return
        _check_filter(filter)
        params: list[Any] = []
        conds = []
        for col, val in filter.items():
            params.append(val)
            conds.append(f"{col} = ${len(params)}")
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        async with self._pool.acquire() as conn:
            await conn.execute(f"DELETE FROM {_TABLE}{where}", *params)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._pool.close()
