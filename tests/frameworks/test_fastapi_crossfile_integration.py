"""ENH-011 end-to-end: index a multi-file FastAPI app → cross-file route-prefix
composition (``include_router(prefix=…)``) and DI grounding (``Depends`` →
provider symbol), with incremental == full idempotency and the ``ckg routes``
CLI surfacing the composed path."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.cli import main
from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.ingest import CodeGraph

FIXTURES = Path(__file__).parent / "fixtures" / "fastapi_multifile"


@pytest.fixture
async def app_graph(tmp_path: Path) -> AsyncIterator[tuple[CodeGraph, Path]]:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield cg, repo
    finally:
        await cg.close()


async def test_router_prefix_composed_onto_included_routes(
    app_graph: tuple[CodeGraph, Path],
) -> None:
    cg, _ = app_graph
    by_base = {r.path: r for r in await cg.routes()}
    # routes on the included router gain the mount prefix in path_pattern, while
    # the immutable base path is preserved.
    assert by_base["/charge"].path_pattern == "/api/charge"
    assert by_base["/charge"].path == "/charge"
    assert by_base["/refund"].path_pattern == "/api/refund"
    # a route hung off `app` (not the mounted router) is unchanged.
    assert by_base["/me"].path_pattern == "/me"
    assert cg.stats().route_prefixes_composed == 2
    assert cg.stats().framework_unresolved == 0


async def test_mount_marker_recorded(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    mounts = (
        await cg.store.graph.query(GraphQuery(kinds=[NodeKind.ROUTE_MOUNT], limit=100))
    ).nodes
    assert len(mounts) == 1
    m = mounts[0]
    assert m.attrs["router_ref"] == "routes.router"
    assert m.attrs["router_var"] == "router"
    assert m.attrs["prefix"] == "/api"
    assert SymbolID.parse(m.id).path == "main.py"  # owned by the mounting file


async def test_di_provider_grounded_cross_file(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    assert cg.stats().di_providers_grounded == 1
    services = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.SERVICE], limit=100))).nodes
    svc = next(s for s in services if s.attrs.get("provider") == "get_db")
    out = await cg.store.graph.adjacent(svc.id, [EdgeKind.PROVIDED_BY], direction="out")
    assert len(out) == 1
    # PROVIDED_BY points at the get_db function defined in db.py.
    target = SymbolID.parse(out[0].dst)
    assert target.path == "db.py" and "get_db" in target.descriptor
    assert svc.attrs["provider_symbol"] == out[0].dst


async def test_cross_file_idempotent_across_incremental(
    app_graph: tuple[CodeGraph, Path],
) -> None:
    # Editing the routes file re-runs pass-2; the composed path_pattern and the
    # PROVIDED_BY edge must converge to the full-index result (no duplication,
    # no stale prefix). The mount lives in main.py — unchanged — so the prefix
    # must still re-apply.
    cg, repo = app_graph
    (repo / "payments" / "routes.py").write_text(
        (repo / "payments" / "routes.py").read_text() + "\n# touch\n"
    )
    await cg.refresh()

    by_base = {r.path: r for r in await cg.routes()}
    assert by_base["/charge"].path_pattern == "/api/charge"
    assert by_base["/refund"].path_pattern == "/api/refund"
    assert cg.stats().route_prefixes_composed == 2

    services = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.SERVICE], limit=100))).nodes
    svc = next(s for s in services if s.attrs.get("provider") == "get_db")
    out = await cg.store.graph.adjacent(svc.id, [EdgeKind.PROVIDED_BY], direction="out")
    assert len(out) == 1  # exactly one PROVIDED_BY, not duplicated


async def test_unmounting_clears_prefix(app_graph: tuple[CodeGraph, Path]) -> None:
    # Remove the prefix from the mount; pass-2 recomputes from the base path, so
    # the composed pattern reverts (proves path_pattern is never a stale write).
    cg, repo = app_graph
    text = (repo / "main.py").read_text().replace('prefix="/api"', 'prefix=""')
    (repo / "main.py").write_text(text)
    await cg.refresh()
    by_base = {r.path: r for r in await cg.routes()}
    assert by_base["/charge"].path_pattern == "/charge"
    assert cg.stats().route_prefixes_composed == 0


def test_ckg_routes_cli_shows_composed_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    assert main(["routes", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "/api/charge" in out and "[base /charge]" in out
