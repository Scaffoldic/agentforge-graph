"""feat-011 end-to-end: index a Django app → DataModel/HAS_FIELD/RELATES_TO in
the graph, CodeGraph.models(), and the ckg models CLI."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.cli import main
from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind
from agentforge_graph.ingest import CodeGraph

FIXTURES = Path(__file__).parent / "fixtures" / "django"


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
    assert cg.stats().models_extracted == 4
    nodes = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.DATA_MODEL], limit=100))).nodes
    assert {n.name for n in nodes} == {"TimestampedModel", "auth_user", "Tag", "Post"}


async def test_models_api(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    models = {m.name: m for m in await cg.models()}
    assert models["auth_user"].table == "auth_user"
    assert models["auth_user"].framework == "django"
    assert models["auth_user"].fields == ["email", "name"]
    post = models["Post"]
    assert post.fields == ["author", "title"]  # FK column included, M2M excluded


async def test_relates_to_fk_and_m2m_resolved(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = app_graph
    assert cg.stats().relations_resolved == 2  # Post->User (fk) + Post->Tag (m2m)
    nodes = {
        n.attrs.get("model_class"): n
        for n in (
            await cg.store.graph.query(GraphQuery(kinds=[NodeKind.DATA_MODEL], limit=100))
        ).nodes
    }
    out = await cg.store.graph.adjacent(nodes["Post"].id, [EdgeKind.RELATES_TO], direction="out")
    by_kind = {e.attrs["kind"]: e.dst for e in out}
    assert by_kind == {"fk": nodes["User"].id, "m2m": nodes["Tag"].id}


async def test_models_survive_incremental_edit(app_graph: tuple[CodeGraph, Path]) -> None:
    cg, repo = app_graph
    text = (repo / "models.py").read_text().replace('db_table = "auth_user"', 'db_table = "people"')
    (repo / "models.py").write_text(text)
    await cg.refresh()
    tables = {m.table for m in await cg.models()}
    assert "people" in tables and "auth_user" not in tables


def test_ckg_models_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    assert main(["models", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "auth_user" in out and "models.py" in out and "author" in out
