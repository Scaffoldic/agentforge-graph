"""feat-011 end-to-end: index a Flask app → Route/HANDLED_BY in the graph,
CodeGraph.routes(), and the ckg routes CLI."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.cli import main
from agentforge_graph.core import GraphQuery, NodeKind
from agentforge_graph.ingest import CodeGraph

FIXTURES = Path(__file__).parent / "fixtures" / "flask"


@pytest.fixture
async def app_graph(tmp_path: Path) -> AsyncIterator[tuple[CodeGraph, Path]]:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield cg, repo
    finally:
        await cg.close()


async def test_index_extracts_routes(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    assert cg.stats().routes_extracted == 4  # GET/POST users + GET health + GET items
    assert cg.stats().framework_unresolved == 1  # the dynamic-path route
    nodes = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.ROUTE], limit=100))).nodes
    assert all(n.attrs["framework"] == "flask" for n in nodes)


async def test_routes_api(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    routes = await cg.routes()
    assert ("POST", "/users/<int:uid>") in [(r.method, r.path) for r in routes]


def test_ckg_routes_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    assert main(["routes", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "/health" in out and "/items" in out
