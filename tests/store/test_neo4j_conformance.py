"""Run feat-003's GraphStoreConformance against the Neo4j server adapter (ENH-004).

Env-gated like the live-model tests: skipped unless ``CKG_NEO4J_URI`` points at a
reachable Neo4j (CI has no server). Run locally against a container, e.g.:

    docker run -d --name ckg-neo4j -e NEO4J_AUTH=neo4j/ckgckgckg -p 7688:7687 neo4j:5
    CKG_NEO4J_URI=bolt://localhost:7688 CKG_NEO4J_PASSWORD=ckgckgckg \\
      uv run pytest tests/store/test_neo4j_conformance.py
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from agentforge_graph.core.conformance import GraphStoreConformance

_URI = os.environ.get("CKG_NEO4J_URI")
pytestmark = pytest.mark.skipif(not _URI, reason="set CKG_NEO4J_URI to run Neo4j conformance")


def _config() -> dict[str, str]:
    return {
        "uri": _URI or "",
        "user": os.environ.get("CKG_NEO4J_USER", "neo4j"),
        "password": os.environ.get("CKG_NEO4J_PASSWORD", ""),
    }


async def _fresh_store() -> AsyncIterator:
    from agentforge_graph.store.neo4j_store import Neo4jGraphStore

    store = await Neo4jGraphStore.open("unused", _config())
    # a fresh, empty graph for every test (shared server)
    async with store._driver.session(database=store._database) as s:
        await s.run("MATCH (n:CkgNode) DETACH DELETE n")
    try:
        yield store
    finally:
        await store.close()


class TestNeo4jGraphStore(GraphStoreConformance):
    @pytest.fixture
    async def store(self) -> AsyncIterator:
        async for s in _fresh_store():
            yield s


async def test_neo4j_close_is_idempotent() -> None:
    from agentforge_graph.store.neo4j_store import Neo4jGraphStore

    store = await Neo4jGraphStore.open("unused", _config())
    await store.close()
    await store.close()
