"""Run feat-015's QueryConformance through the AST interpreter (chunk 4).

The interpreter is the query path for backends with no native query language
(SurrealDB). Here it runs over an *embedded Kuzu* store as the data source, so
the interpreter logic is proven in CI with no server — the same query set must
return the same canonical rows as the compiled Kuzu path. The live-SurrealDB
subclass (env-gated) then confirms it against the real backend.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import GraphStore
from agentforge_graph.store import KuzuGraphStore
from agentforge_graph.store.query.ast import QueryAst
from agentforge_graph.store.query.capability import (
    AGG_COLLECT,
    CORE_TIER,
    QuerySettings,
    ResultTable,
)
from agentforge_graph.store.query.conformance import QueryConformance
from agentforge_graph.store.query.interpret import InterpretingQueryEngine


class _InterpretedStore:
    """A QueryCapable store that stores via a real backend but *interprets*
    queries over the ABC — exercises the interpreter without a live server."""

    query_dialect = "interpreted"
    capabilities = CORE_TIER | {AGG_COLLECT}
    read_only_execution = True

    def __init__(self, backing: GraphStore) -> None:
        self._backing = backing

    async def upsert(self, subgraph: object) -> None:
        await self._backing.upsert(subgraph)  # type: ignore[arg-type]

    async def run_query(self, ast: QueryAst, settings: QuerySettings) -> ResultTable:
        return await InterpretingQueryEngine(self._backing).run(ast, settings)


class TestInterpretedQuery(QueryConformance):
    @pytest.fixture
    async def store(self, tmp_path: Path) -> AsyncIterator[_InterpretedStore]:
        backing = await KuzuGraphStore.open(tmp_path / "graph.kuzu")
        try:
            yield _InterpretedStore(backing)
        finally:
            await backing.close()
