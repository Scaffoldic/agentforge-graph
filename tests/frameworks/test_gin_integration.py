"""ENH-012 end-to-end: index a Gin app → Route/HANDLED_BY in the graph,
CodeGraph.routes(), and the ckg routes CLI. Confirms the named handler edge
lands on the real Go function node and detection rides the import marker."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.cli import main
from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.ingest import CodeGraph

FIXTURES = Path(__file__).parent / "fixtures" / "gin"


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
    # GET /ping, POST /users, DELETE /users/:id (anonymous) — the dynamic path
    # is counted, not extracted.
    assert cg.stats().routes_extracted == 3
    assert cg.stats().framework_unresolved == 1
    nodes = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.ROUTE], limit=100))).nodes
    assert all(n.attrs["framework"] == "gin" for n in nodes)


async def test_routes_api(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    routes = {(r.method, r.path) for r in await cg.routes()}
    assert routes == {("GET", "/ping"), ("POST", "/users"), ("DELETE", "/users/:id")}


async def test_handled_by_lands_on_real_function(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    routes = {
        r.attrs["path"]: r
        for r in (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.ROUTE], limit=100))).nodes
    }
    out = await cg.store.graph.adjacent(routes["/ping"].id, [EdgeKind.HANDLED_BY], direction="out")
    assert len(out) == 1
    target = await cg.store.graph.get(out[0].dst)
    assert target is not None and target.kind is NodeKind.FUNCTION
    assert SymbolID.parse(out[0].dst).descriptor == "ping()."
    assert SymbolID.parse(out[0].dst).path == "main.go"
    # the anonymous DELETE handler yields a Route but no HANDLED_BY edge
    anon = await cg.store.graph.adjacent(
        routes["/users/:id"].id, [EdgeKind.HANDLED_BY], direction="out"
    )
    assert anon == []


def test_ckg_routes_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    assert main(["routes", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "/ping" in out and "/users" in out and "main.go" in out


async def test_no_gin_no_routes(tmp_path: Path) -> None:
    repo = tmp_path / "plain"
    repo.mkdir()
    (repo / "go.mod").write_text("module plain\ngo 1.21\n")
    (repo / "m.go").write_text("package main\nfunc f() int { return 1 }\n")
    cg = await CodeGraph.index(repo_path=repo)
    try:
        assert cg.stats().routes_extracted == 0
        assert await cg.routes() == []
    finally:
        await cg.close()
