"""feat-011 end-to-end: index a NestJS app → Route/HANDLED_BY in the graph,
CodeGraph.routes(), and the ckg routes CLI. Confirms the handler edge lands on
the real TS method node."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.cli import main
from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.ingest import CodeGraph

FIXTURES = Path(__file__).parent / "fixtures" / "nestjs"


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
    assert cg.stats().routes_extracted == 4
    nodes = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.ROUTE], limit=100))).nodes
    assert all(n.attrs["framework"] == "nestjs" for n in nodes)


async def test_handled_by_lands_on_real_method(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    route = next(
        n
        for n in (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.ROUTE], limit=100))).nodes
        if n.name == "POST /users"
    )
    nbrs = await cg.store.graph.neighbors(route.id, [EdgeKind.HANDLED_BY], depth=1)
    assert [n.kind for n in nbrs] == [NodeKind.METHOD]
    assert SymbolID.parse(nbrs[0].id).descriptor == "UsersController#create()."


def test_ckg_routes_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    assert main(["routes", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "/users" in out
