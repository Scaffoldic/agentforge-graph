"""Run feat-015's QueryConformance against the SurrealDB adapter (chunk 4).

SurrealDB has no native graph traversal, so it executes queries via the portable
AST interpreter over the GraphStore ABC. This env-gated live test confirms the
interpreter returns the same canonical rows against the real SurrealDB backend
that it does over Kuzu — result parity across all three backends.

    docker run -d --name ckg-surreal -p 8000:8000 \\
      surrealdb/surrealdb:latest start --user root --pass root
    CKG_SURREALDB_URL=ws://localhost:8000/rpc \\
      uv run pytest tests/store/test_surreal_query_conformance.py
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from agentforge_graph.store.query.conformance import QueryConformance

_URL = os.environ.get("CKG_SURREALDB_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="set CKG_SURREALDB_URL to run SurrealDB query conformance"
)


class TestSurrealQuery(QueryConformance):
    @pytest.fixture
    async def store(self) -> AsyncIterator:
        from agentforge_graph.store.surreal_store import SurrealGraphStore

        config = {
            "url": _URL or "",
            "username": os.environ.get("CKG_SURREALDB_USER", "root"),
            "password": os.environ.get("CKG_SURREALDB_PASS", "root"),
        }
        store = await SurrealGraphStore.open("unused", config)
        await store._db.query("DELETE ckg_node; DELETE ckg_edge")  # fresh graph per test
        try:
            yield store
        finally:
            await store.close()
