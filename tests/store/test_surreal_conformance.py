"""Run feat-003's GraphStore + VectorStore conformance against the SurrealDB
single-server adapter (ENH-010). SurrealDB is multi-model, so one backend covers
both roles.

Env-gated like the other server adapters: skipped unless ``CKG_SURREALDB_URL``
points at a reachable SurrealDB (the base CI job has no server). Run locally:

    docker run -d --name ckg-surreal -p 8000:8000 \\
      surrealdb/surrealdb:latest start --user root --pass root memory
    CKG_SURREALDB_URL=ws://localhost:8000/rpc \\
      uv run pytest tests/store/test_surreal_conformance.py
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from agentforge_graph.core.conformance import GraphStoreConformance, VectorStoreConformance

_URL = os.environ.get("CKG_SURREALDB_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="set CKG_SURREALDB_URL to run SurrealDB conformance"
)


def _config() -> dict[str, str]:
    return {
        "url": _URL or "",
        "username": os.environ.get("CKG_SURREALDB_USER", "root"),
        "password": os.environ.get("CKG_SURREALDB_PASS", "root"),
    }


async def _clean(db: object) -> None:
    # a fresh, empty store for every test (shared server)
    await db.query("DELETE ckg_node; DELETE ckg_edge; DELETE ckg_vector")  # type: ignore[attr-defined]


class TestSurrealGraphStore(GraphStoreConformance):
    @pytest.fixture
    async def store(self) -> AsyncIterator:
        from agentforge_graph.store.surreal_store import SurrealGraphStore

        store = await SurrealGraphStore.open("unused", _config())
        await _clean(store._db)
        try:
            yield store
        finally:
            await store.close()


class TestSurrealVectorStore(VectorStoreConformance):
    @pytest.fixture
    async def vectors(self) -> AsyncIterator:
        from agentforge_graph.store.surreal_store import SurrealVectorStore

        store = await SurrealVectorStore.open("unused", _config())
        await _clean(store._db)
        try:
            yield store
        finally:
            await store.close()


async def test_surreal_close_is_idempotent() -> None:
    from agentforge_graph.store.surreal_store import SurrealGraphStore

    store = await SurrealGraphStore.open("unused", _config())
    await store.close()
    await store.close()
