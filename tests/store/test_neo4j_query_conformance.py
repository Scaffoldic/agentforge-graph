"""Run feat-015's QueryConformance against the Neo4j adapter (chunk 3).

Env-gated like the storage conformance: skipped unless ``CKG_NEO4J_URI`` points
at a reachable Neo4j. Proves the Cypher compiler + bounds are backend-portable —
the same query set must return the same rows as Kuzu.

    docker run -d --name ckg-neo4j -e NEO4J_AUTH=neo4j/ckgckgckg -p 7688:7687 neo4j:5
    CKG_NEO4J_URI=bolt://localhost:7688 CKG_NEO4J_PASSWORD=ckgckgckg \\
      uv run pytest tests/store/test_neo4j_query_conformance.py
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from agentforge_graph.store.query.conformance import QueryConformance

_URI = os.environ.get("CKG_NEO4J_URI")
pytestmark = pytest.mark.skipif(not _URI, reason="set CKG_NEO4J_URI to run Neo4j query conformance")


class TestNeo4jQuery(QueryConformance):
    @pytest.fixture
    async def store(self) -> AsyncIterator:
        from agentforge_graph.store.neo4j_store import Neo4jGraphStore

        config = {
            "uri": _URI or "",
            "user": os.environ.get("CKG_NEO4J_USER", "neo4j"),
            "password": os.environ.get("CKG_NEO4J_PASSWORD", ""),
        }
        store = await Neo4jGraphStore.open("unused", config)
        async with store._driver.session(database=store._database) as s:
            await s.run("MATCH (n:CkgNode) DETACH DELETE n")  # fresh graph per test
        try:
            yield store
        finally:
            await store.close()
