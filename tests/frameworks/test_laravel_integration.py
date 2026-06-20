"""ENH-012 end-to-end: index a Laravel app (routes file + a controller in
another file) → routes whose HANDLED_BY is grounded cross-file to the real PHP
controller method by the generic pass-2, plus incremental idempotency."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.ingest import CodeGraph

FIXTURES = Path(__file__).parent / "fixtures" / "laravel"


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
    assert cg.stats().routes_extracted == 3  # 2 controller routes + 1 closure
    routes = {(r.method, r.path) for r in await cg.routes()}
    assert routes == {("GET", "/users"), ("POST", "/users"), ("GET", "/health")}


async def test_handlers_grounded_cross_file(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    assert cg.stats().route_handlers_grounded == 2  # the closure route has no controller
    routes = {
        (r.attrs["method"], r.attrs["path"]): r
        for r in (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.ROUTE], limit=100))).nodes
    }
    out = await cg.store.graph.adjacent(
        routes[("GET", "/users")].id, [EdgeKind.HANDLED_BY], direction="out"
    )
    # /users (GET) → UserController#index, defined in another file
    target = await cg.store.graph.get(out[0].dst)
    assert target is not None and target.kind is NodeKind.METHOD
    parsed = SymbolID.parse(out[0].dst)
    assert parsed.descriptor == "UserController#index()."
    assert parsed.path.endswith("UserController.php")
    # the closure route stays unlinked
    closure = await cg.store.graph.adjacent(
        routes[("GET", "/health")].id, [EdgeKind.HANDLED_BY], direction="out"
    )
    assert closure == []


async def test_grounding_idempotent_across_incremental(
    app_graph: tuple[CodeGraph, Path],
) -> None:
    cg, repo = app_graph
    (repo / "routes" / "web.php").write_text(
        (repo / "routes" / "web.php").read_text()
        + "\nRoute::get('/x', function () { return 1; });\n"
    )
    await cg.refresh()
    assert cg.stats().route_handlers_grounded == 2
    routes = {
        (r.attrs["method"], r.attrs["path"]): r
        for r in (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.ROUTE], limit=100))).nodes
    }
    out = await cg.store.graph.adjacent(
        routes[("GET", "/users")].id, [EdgeKind.HANDLED_BY], direction="out"
    )
    assert len(out) == 1  # not duplicated
