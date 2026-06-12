"""Run feat-001's GraphStoreConformance against the Kuzu adapter, proving
it is interchangeable with the in-memory reference."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core.conformance import GraphStoreConformance
from agentforge_graph.store import KuzuGraphStore


class TestKuzuGraphStore(GraphStoreConformance):
    @pytest.fixture
    async def store(self, tmp_path: Path) -> AsyncIterator[KuzuGraphStore]:
        s = await KuzuGraphStore.open(tmp_path / "graph.kuzu")
        try:
            yield s
        finally:
            await s.close()
