"""Symbol ranking: PageRank surfaces the most-called symbol; focus re-ranks."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.config import _default_edge_weights
from agentforge_graph.core import NodeKind
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.repomap.rank import rank_symbols

FIXTURES = Path(__file__).parent.parent / "ingest" / "fixtures" / "python"
_KINDS = [NodeKind.CLASS, NodeKind.FUNCTION, NodeKind.METHOD]


@pytest.fixture
async def cg(tmp_path: Path) -> AsyncIterator[CodeGraph]:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    graph = await CodeGraph.index(repo_path=repo)  # CALLS edges resolved at index
    try:
        yield graph
    finally:
        await graph.close()


async def test_most_called_symbol_ranks_top(cg: CodeGraph) -> None:
    ranked = await rank_symbols(cg.store, _KINDS, 0.85, _default_edge_weights())
    assert ranked
    # square() is called by cube() and area() -> highest in-degree -> top rank
    assert ranked[0].name == "square"
    assert ranked[0].signature.startswith("def square")


async def test_ranks_are_sorted_descending(cg: CodeGraph) -> None:
    ranked = await rank_symbols(cg.store, _KINDS, 0.85, _default_edge_weights())
    ranks = [r.rank for r in ranked]
    assert ranks == sorted(ranks, reverse=True)


async def test_focus_reranks_toward_focus_file(cg: CodeGraph) -> None:
    base = await rank_symbols(cg.store, _KINDS, 0.85, _default_edge_weights())
    focused = await rank_symbols(
        cg.store, _KINDS, 0.85, _default_edge_weights(), focus=["shapes.py"]
    )
    # a shapes.py symbol gains rank-share under focus on shapes.py
    circle_base = next(r.rank for r in base if r.name == "Circle")
    circle_focus = next(r.rank for r in focused if r.name == "Circle")
    assert circle_focus > circle_base


async def test_scope_restricts_symbols(cg: CodeGraph) -> None:
    ranked = await rank_symbols(
        cg.store, _KINDS, 0.85, _default_edge_weights(), scope="mathutils.py"
    )
    assert {r.name for r in ranked} == {"square", "cube"}


async def test_signatures_present(cg: CodeGraph) -> None:
    ranked = await rank_symbols(cg.store, _KINDS, 0.85, _default_edge_weights())
    assert all(r.signature for r in ranked)  # every symbol has its def/class line
