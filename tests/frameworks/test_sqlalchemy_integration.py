"""feat-011 end-to-end: index a SQLAlchemy app → DataModel/HAS_FIELD in the
graph, CodeGraph.models(), incrementality, and the ckg models CLI."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.cli import main
from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind
from agentforge_graph.ingest import CodeGraph

FIXTURES = Path(__file__).parent / "fixtures" / "sqlalchemy"


@pytest.fixture
async def app_graph(tmp_path: Path) -> AsyncIterator[tuple[CodeGraph, Path]]:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield cg, repo
    finally:
        await cg.close()


async def test_index_extracts_models(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    report = cg.stats()
    assert report.models_extracted == 2
    nodes = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.DATA_MODEL], limit=100))).nodes
    assert {n.name for n in nodes} == {"users", "posts"}


async def test_models_api(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    models = await cg.models()
    assert [m.name for m in models] == ["posts", "users"]
    users = next(m for m in models if m.name == "users")
    assert users.table == "users"
    assert users.framework == "sqlalchemy"
    assert users.fields == ["id", "name"]  # relationship() is not a column field
    assert users.file == "models.py" and users.line >= 1
    assert users.cls.endswith("User#") or "User#" in users.cls


async def test_has_field_edges_in_graph(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    model = next(
        n
        for n in (
            await cg.store.graph.query(GraphQuery(kinds=[NodeKind.DATA_MODEL], limit=100))
        ).nodes
        if n.name == "posts"
    )
    fields = await cg.store.graph.neighbors(model.id, [EdgeKind.HAS_FIELD], depth=1)
    assert {f.name for f in fields} == {"id", "title", "author_id"}
    assert all(f.kind is NodeKind.VARIABLE for f in fields)


async def test_relates_to_edges_resolved(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    assert cg.stats().relations_resolved == 2  # User->Post (relationship) + Post->User (fk)
    nodes = {
        n.name: n
        for n in (
            await cg.store.graph.query(GraphQuery(kinds=[NodeKind.DATA_MODEL], limit=100))
        ).nodes
    }
    out = await cg.store.graph.adjacent(nodes["users"].id, [EdgeKind.RELATES_TO], direction="out")
    assert [e.dst for e in out] == [nodes["posts"].id]
    assert out[0].attrs["kind"] == "relationship" and out[0].attrs["via"] == "posts"
    out_post = await cg.store.graph.adjacent(
        nodes["posts"].id, [EdgeKind.RELATES_TO], direction="out"
    )
    assert [(e.dst, e.attrs["kind"]) for e in out_post] == [(nodes["users"].id, "fk")]


async def test_models_api_exposes_relations(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    models = {m.name: m for m in await cg.models()}
    assert models["users"].relations == [{"to": "posts", "kind": "relationship", "via": "posts"}]
    assert models["posts"].relations == [{"to": "users", "kind": "fk", "via": "author_id"}]


async def test_relates_to_idempotent_across_incremental(app_graph: tuple[CodeGraph, Path]) -> None:
    # a no-op-ish edit re-runs pass-2; RELATES_TO must not duplicate (global
    # clear + rebuild = incremental converges to the full-index graph).
    cg, repo = app_graph
    (repo / "models.py").write_text((repo / "models.py").read_text() + "\n# touch\n")
    await cg.refresh()
    nodes = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.DATA_MODEL], limit=100))).nodes
    users = next(n for n in nodes if n.name == "users")
    out = await cg.store.graph.adjacent(users.id, [EdgeKind.RELATES_TO], direction="out")
    assert len(out) == 1  # exactly one User->Post, not duplicated


async def test_models_survive_incremental_edit(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, repo = app_graph
    text = (
        (repo / "models.py")
        .read_text()
        .replace('__tablename__ = "users"', '__tablename__ = "people"')
    )
    (repo / "models.py").write_text(text)
    await cg.refresh()
    tables = {m.table for m in await cg.models()}
    assert "people" in tables and "users" not in tables


def test_ckg_models_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    assert main(["models", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "users" in out and "models.py" in out and "id" in out


async def test_no_framework_no_models(tmp_path: Path) -> None:
    repo = tmp_path / "plain"
    repo.mkdir()
    (repo / "m.py").write_text("def f():\n    return 1\n")
    cg = await CodeGraph.index(repo_path=repo)
    try:
        assert cg.stats().models_extracted == 0
        assert await cg.models() == []
    finally:
        await cg.close()
