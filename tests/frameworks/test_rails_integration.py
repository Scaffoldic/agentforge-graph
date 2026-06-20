"""ENH-012 end-to-end: index a Rails app (config/routes.rb + controllers in
other files) → routes whose HANDLED_BY is grounded cross-file to the real Ruby
controller method by the generic pass-2."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.ingest import CodeGraph

FIXTURES = Path(__file__).parent / "fixtures" / "rails"


@pytest.fixture
async def app_graph(tmp_path: Path) -> AsyncIterator[tuple[CodeGraph, Path]]:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield cg, repo
    finally:
        await cg.close()


async def test_routes_extracted(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    # get /users, post /users, root (GET /) — resources :photos is counted only.
    assert cg.stats().routes_extracted == 3
    routes = {(r.method, r.path) for r in await cg.routes()}
    assert routes == {("GET", "/users"), ("POST", "/users"), ("GET", "/")}


async def test_handlers_grounded_cross_file(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    # 3 routes ground to UsersController#index/create + HomeController#show.
    assert cg.stats().route_handlers_grounded == 3
    routes = {
        (r.attrs["method"], r.attrs["path"]): r
        for r in (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.ROUTE], limit=100))).nodes
    }
    out = await cg.store.graph.adjacent(
        routes[("POST", "/users")].id, [EdgeKind.HANDLED_BY], direction="out"
    )
    target = await cg.store.graph.get(out[0].dst)
    assert target is not None and target.kind is NodeKind.METHOD
    parsed = SymbolID.parse(out[0].dst)
    assert parsed.descriptor == "UsersController#create()."
    assert parsed.path.endswith("users_controller.rb")


def test_ckg_routes_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from agentforge_graph.cli import main

    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    assert main(["routes", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "/users" in out and "routes.rb" in out
