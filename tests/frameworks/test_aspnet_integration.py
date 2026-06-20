"""ENH-012 end-to-end: index an ASP.NET controller → Route/HANDLED_BY in the
graph, CodeGraph.routes(), and the ckg routes CLI. Confirms the handler edge
lands on the real C# Method node."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.cli import main
from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.ingest import CodeGraph

FIXTURES = Path(__file__).parent / "fixtures" / "aspnet"


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
    assert cg.stats().routes_extracted == 2
    nodes = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.ROUTE], limit=100))).nodes
    assert all(n.attrs["framework"] == "aspnet" for n in nodes)


async def test_routes_api(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    routes = {(r.method, r.path) for r in await cg.routes()}
    assert routes == {("GET", "/api/Users/{id}"), ("POST", "/api/Users")}


async def test_handled_by_lands_on_real_method(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    route = next(
        n
        for n in (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.ROUTE], limit=100))).nodes
        if n.attrs["path"] == "/api/Users/{id}"
    )
    out = await cg.store.graph.adjacent(route.id, [EdgeKind.HANDLED_BY], direction="out")
    assert len(out) == 1
    target = await cg.store.graph.get(out[0].dst)
    assert target is not None and target.kind is NodeKind.METHOD
    assert SymbolID.parse(out[0].dst).descriptor == "UsersController#Get()."


def test_ckg_routes_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    assert main(["routes", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "/api/Users" in out and "UsersController.cs" in out
