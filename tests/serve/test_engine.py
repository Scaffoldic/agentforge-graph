"""_Engine: lazy open + status (counts, staleness, tool-api version)."""

from __future__ import annotations

import shutil
from pathlib import Path

from agentforge_graph.ingest import CodeGraph
from agentforge_graph.serve.engine import TOOL_API_VERSION, _Engine

FIXTURES = Path(__file__).parent.parent / "ingest" / "fixtures" / "python"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    return repo


async def test_status_reports_counts_and_version(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    cg = await CodeGraph.index(repo_path=repo)
    await cg.close()
    engine = _Engine(repo)
    try:
        status = await engine.status()
        assert status["nodes"] > 0
        assert status["by_kind"].get("Class") == 1
        assert status["tool_api_version"] == TOOL_API_VERSION
        assert "dirty" in status
    finally:
        await engine.close()


async def test_engine_lazy_and_cached(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    cg = await CodeGraph.index(repo_path=repo)
    await cg.close()
    engine = _Engine(repo)
    try:
        r1 = await engine.retriever()
        r2 = await engine.retriever()
        assert r1 is r2  # cached
        rm = await engine.repomap()
        assert rm is not None
    finally:
        await engine.close()


async def test_status_not_dirty_when_no_git(tmp_path: Path) -> None:
    # fixture index has no git repo -> indexed_commit empty -> dirty False
    repo = _repo(tmp_path)
    cg = await CodeGraph.index(repo_path=repo)
    await cg.close()
    engine = _Engine(repo)
    try:
        assert (await engine.status())["dirty"] is False
    finally:
        await engine.close()
