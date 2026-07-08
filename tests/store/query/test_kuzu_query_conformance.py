"""Run feat-015's QueryConformance against the Kuzu adapter (chunk 2).

Kuzu is embedded, so this is the always-on CI gate for the query surface; the
Neo4j and SurrealDB subclasses (chunks 3-4) run the same suite env-gated.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.store import KuzuGraphStore
from agentforge_graph.store.query.conformance import QueryConformance


class TestKuzuQuery(QueryConformance):
    @pytest.fixture
    async def store(self, tmp_path: Path) -> AsyncIterator[KuzuGraphStore]:
        s = await KuzuGraphStore.open(tmp_path / "graph.kuzu")
        try:
            yield s
        finally:
            await s.close()
