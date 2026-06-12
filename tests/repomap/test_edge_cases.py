"""Repo map edge cases: empty graph, edgeless graph, determinism."""

from __future__ import annotations

import shutil
from pathlib import Path

from agentforge_graph.config import RepoMapConfig, _default_edge_weights
from agentforge_graph.core import NodeKind
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.repomap import RepoMap
from agentforge_graph.repomap.rank import rank_symbols

FIXTURES = Path(__file__).parent.parent / "ingest" / "fixtures" / "python"
_KINDS = [NodeKind.CLASS, NodeKind.FUNCTION, NodeKind.METHOD]


async def test_empty_repo_yields_empty_map(tmp_path: Path) -> None:
    repo = tmp_path / "empty"
    repo.mkdir()
    (repo / "blank.py").write_text("# only a comment\nx = 1\n")
    cg = await CodeGraph.index(repo_path=repo)
    try:
        assert await cg.repo_map(budget_tokens=2000) == ""
        assert await cg.ranked_symbols() == []
    finally:
        await cg.close()


async def test_edgeless_graph_ranks_uniformly_no_error(tmp_path: Path) -> None:
    repo = tmp_path / "iso"
    repo.mkdir()
    (repo / "iso.py").write_text("def a():\n    return 1\n\n\ndef b():\n    return 2\n")
    cg = await CodeGraph.index(repo_path=repo)
    try:
        ranked = await rank_symbols(cg.store, _KINDS, 0.85, _default_edge_weights())
        assert {r.name for r in ranked} == {"a", "b"}
        assert abs(ranked[0].rank - ranked[1].rank) < 1e-6  # uniform
    finally:
        await cg.close()


async def test_ranking_is_deterministic(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        rm = RepoMap(cg.store, RepoMapConfig())
        a = [(r.id, r.rank) for r in await rm.ranked_symbols()]
        b = [(r.id, r.rank) for r in await rm.ranked_symbols()]
        assert a == b
    finally:
        await cg.close()
