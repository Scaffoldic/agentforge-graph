"""Run feat-003's VectorStoreConformance against the pgvector server adapter
(ENH-004). Env-gated: skipped unless ``CKG_PGVECTOR_DSN`` points at a reachable
Postgres with the pgvector extension available. Run locally against a container:

    docker run -d --name ckg-pg -e POSTGRES_PASSWORD=ckg -e POSTGRES_DB=ckg \\
      -p 5433:5432 pgvector/pgvector:pg16
    CKG_PGVECTOR_DSN=postgresql://postgres:ckg@localhost:5433/ckg \\
      uv run pytest tests/store/test_pgvector_conformance.py
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from agentforge_graph.core.conformance import VectorStoreConformance, make_sample_embeddings

_DSN = os.environ.get("CKG_PGVECTOR_DSN")
pytestmark = pytest.mark.skipif(not _DSN, reason="set CKG_PGVECTOR_DSN to run pgvector conformance")


async def _fresh_store() -> AsyncIterator:
    from agentforge_graph.store.pgvector_store import PgVectorStore

    store = await PgVectorStore.open("unused", {"dsn": _DSN})
    # a fresh, empty table for every test (shared server)
    async with store._pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS ckg_vectors")
    store._dim = None
    try:
        yield store
    finally:
        await store.close()


class TestPgVectorStore(VectorStoreConformance):
    @pytest.fixture
    async def vectors(self) -> AsyncIterator:
        async for v in _fresh_store():
            yield v


async def test_pgvector_empty_upsert_is_noop() -> None:
    async for v in _fresh_store():
        await v.upsert([])
        assert await v.search([0.0] * 8, k=5) == []


async def test_pgvector_search_before_table() -> None:
    async for v in _fresh_store():
        assert await v.search([1.0] * 8, k=3) == []


async def test_pgvector_unfilterable_column_rejected() -> None:
    async for v in _fresh_store():
        await v.upsert(make_sample_embeddings())
        with pytest.raises(ValueError, match="unfilterable"):
            await v.delete_where({"ordinal": 0})


async def test_pgvector_score_is_cosine_similarity() -> None:
    async for v in _fresh_store():
        items = make_sample_embeddings()  # orthogonal one-hot vectors
        await v.upsert(items)
        hits = await v.search(items[1].vector, k=3)
        assert hits[0].ref == items[1].ref
        assert hits[0].score == pytest.approx(1.0, abs=1e-3)  # identical → similarity 1
        assert all(0.0 <= h.score <= 1.0 for h in hits)
