"""feat-011 end-to-end: index a FastAPI app → Route/HANDLED_BY in the graph,
CodeGraph.routes(), incrementality, the ckg_routes tool, ckg routes CLI, and
the negative (no framework) path."""

from __future__ import annotations

import json
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.cli import main
from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.ingest import CodeGraph

FIXTURES = Path(__file__).parent / "fixtures" / "fastapi"


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
    report = cg.stats()
    assert report.routes_extracted == 2
    assert report.framework_unresolved == 1  # the dynamic-path route
    route_nodes = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.ROUTE], limit=100))).nodes
    assert {n.name for n in route_nodes} == {"GET /health", "POST /payments/{pid}/refund"}


async def test_routes_api(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    routes = await cg.routes()
    assert [(r.method, r.path) for r in routes] == [
        ("GET", "/health"),
        ("POST", "/payments/{pid}/refund"),
    ]
    assert routes[0].file == "app.py" and routes[0].line >= 1


async def test_handled_by_edge_in_graph(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    route = next(
        n
        for n in (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.ROUTE], limit=100))).nodes
        if n.name == "POST /payments/{pid}/refund"
    )
    nbrs = await cg.store.graph.neighbors(route.id, [EdgeKind.HANDLED_BY], depth=1)
    assert [n.kind for n in nbrs] == [NodeKind.FUNCTION]
    assert SymbolID.parse(nbrs[0].id).descriptor == "refund()."


async def test_routes_survive_incremental_edit(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, repo = app_graph
    text = (repo / "app.py").read_text().replace('@app.get("/health")', '@app.get("/healthz")')
    (repo / "app.py").write_text(text)
    await cg.refresh()
    routes = await cg.routes()
    paths = {r.path for r in routes}
    assert "/healthz" in paths and "/health" not in paths


async def test_ckg_routes_tool(app_graph: tuple[CodeGraph, Path]) -> None:
    from agentforge_graph.serve.engine import _Engine
    from agentforge_graph.serve.tools import CkgRoutes

    _, repo = app_graph
    tool = CkgRoutes(_Engine(repo))
    out = json.loads(await tool.run(method="POST"))
    assert out["count"] == 1
    assert out["routes"][0]["path"] == "/payments/{pid}/refund"
    assert "indexed_commit" in out and out["tool_api_version"]


def test_ckg_routes_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    assert main(["routes", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "GET" in out and "/health" in out and "app.py" in out


async def test_no_framework_no_routes(tmp_path: Path) -> None:
    repo = tmp_path / "plain"
    repo.mkdir()
    (repo / "m.py").write_text("def f():\n    return 1\n")
    cg = await CodeGraph.index(repo_path=repo)
    try:
        assert cg.stats().routes_extracted == 0
        assert await cg.routes() == []
    finally:
        await cg.close()
