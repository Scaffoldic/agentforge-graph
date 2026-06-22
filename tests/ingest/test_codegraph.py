"""End-to-end: CodeGraph.index over the fixture repo, then query the graph
and read the IndexReport; plus open() semantics."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.ingest import CodeGraph


@pytest.fixture
async def indexed(tmp_path: Path, python_repo: Path):
    repo = tmp_path / "proj"
    shutil.copytree(python_repo, repo)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield cg
    finally:
        await cg.close()


async def test_index_report_counts(indexed: CodeGraph) -> None:
    report = indexed.stats()
    assert report.files_indexed == 2
    assert report.by_node_kind.get("Class") == 1
    assert report.by_node_kind.get("Method") == 2  # __init__, area
    assert report.by_node_kind.get("Function") == 3  # square, cube, describe
    assert report.by_edge_kind.get("CALLS") == 2
    assert report.by_edge_kind.get("IMPORTS") == 2
    assert report.resolve.refs_unresolved == 1


async def test_graph_is_queryable_after_index(indexed: CodeGraph) -> None:
    store = indexed.store
    classes = (await store.graph.query(GraphQuery(kinds=[NodeKind.CLASS]))).nodes
    assert {n.name for n in classes} == {"Circle"}
    # cross-file CALLS edge survived into the store
    by_desc = {
        SymbolID.parse(n.id).descriptor: n.id
        for n in (await store.graph.query(GraphQuery(limit=10000))).nodes
    }
    nbrs = await store.graph.neighbors(by_desc["Circle#area()."], [EdgeKind.CALLS], depth=1)
    assert any(SymbolID.parse(n.id).descriptor == "square()." for n in nbrs)


async def test_index_creates_embedded_store(indexed: CodeGraph, tmp_path: Path) -> None:
    assert (tmp_path / "proj" / ".ckg" / "graph.kuzu").exists()


async def test_index_threads_resolved_config(tmp_path: Path, python_repo: Path) -> None:
    """ENH-022: a ResolvedConfig (in-memory merged section) is a drop-in config
    source — the store path from it wins, proving the cascade threads end-to-end
    through CodeGraph without a config file."""
    from agentforge_graph.config import ResolvedConfig

    repo = tmp_path / "proj"
    shutil.copytree(python_repo, repo)
    rc = ResolvedConfig(section={"store": {"path": "custom_ckg"}}, origin="test")
    cg = await CodeGraph.index(repo_path=repo, config=rc)
    try:
        assert (repo / "custom_ckg" / "graph.kuzu").exists()  # path from ResolvedConfig
        assert not (repo / ".ckg").exists()  # default not used
    finally:
        await cg.close()


async def test_open_does_not_index(tmp_path: Path, python_repo: Path) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(python_repo, repo)
    cg = await CodeGraph.index(repo_path=repo)
    await cg.close()
    reopened = await CodeGraph.open(repo_path=repo)
    try:
        # data persisted; stats() raises because open() didn't index
        got = (await reopened.store.graph.query(GraphQuery(kinds=[NodeKind.CLASS]))).nodes
        assert {n.name for n in got} == {"Circle"}
        with pytest.raises(RuntimeError, match="open"):
            reopened.stats()
    finally:
        await reopened.close()


async def test_language_filter_selects_packs(tmp_path: Path, python_repo: Path) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(python_repo, repo)
    # a language that has no pack -> nothing indexed
    cg = await CodeGraph.index(repo_path=repo, languages=["rust"])
    try:
        assert cg.stats().files_indexed == 0
    finally:
        await cg.close()
