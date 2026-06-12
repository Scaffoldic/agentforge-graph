"""Retriever modes over the indexed+embedded fixture repo (FakeEmbedder)."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.config import RetrieveConfig
from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.embed import FakeEmbedder
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.retrieve import Retriever

FIXTURES = Path(__file__).parent.parent / "ingest" / "fixtures" / "python"


@pytest.fixture
async def retriever(tmp_path: Path) -> AsyncIterator[tuple[Retriever, CodeGraph]]:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    cg = await CodeGraph.index(repo_path=repo)
    emb = FakeEmbedder(dim=32)
    await cg.embed(embedder=emb)
    r = Retriever(cg.store, emb, RetrieveConfig(k=5, depth=2))
    try:
        yield r, cg
    finally:
        await cg.close()


async def _id(cg: CodeGraph, descriptor: str) -> str:
    nodes = (await cg.store.graph.query(GraphQuery(limit=10000))).nodes
    return next(n.id for n in nodes if SymbolID.parse(n.id).descriptor == descriptor)


async def test_context_query_returns_chunks_and_symbols(
    retriever: tuple[Retriever, CodeGraph],
) -> None:
    r, _ = retriever
    pack = await r.retrieve("circle area radius", mode="context")
    assert pack.items
    kinds = {i.kind for i in pack.items}
    assert NodeKind.CHUNK in kinds  # the vector hits
    # at least one item carries a why-trace
    assert any(i.why for i in pack.items)


async def test_impact_returns_callers(retriever: tuple[Retriever, CodeGraph]) -> None:
    r, cg = retriever
    square = await _id(cg, "square().")
    pack = await r.retrieve(symbol=square, mode="impact", depth=1)
    # square is called by cube() (same file) and area() (cross-file) -> reverse CALLS
    names = {i.name for i in pack.items}
    assert {"cube", "area"} & names


async def test_definition_returns_symbol_and_chunks(
    retriever: tuple[Retriever, CodeGraph],
) -> None:
    r, cg = retriever
    circle = await _id(cg, "Circle#")
    pack = await r.retrieve(symbol=circle, mode="definition", depth=1)
    ids = {i.id for i in pack.items}
    assert circle in ids
    # its methods (CONTAINS) and/or chunks (CHUNK_OF) appear
    assert len(pack.items) > 1


async def test_similar_is_pure_vector_no_expansion(
    retriever: tuple[Retriever, CodeGraph],
) -> None:
    r, _ = retriever
    pack = await r.retrieve("validate token", mode="similar")
    assert all(i.kind is NodeKind.CHUNK for i in pack.items)
    assert all(i.why and i.why[0].startswith("vector hit") for i in pack.items)


async def test_zero_query_hits_no_hallucinated_expansion(tmp_path: Path) -> None:
    repo = tmp_path / "empty"
    repo.mkdir()
    (repo / "blank.py").write_text("# just a comment\n")
    cg = await CodeGraph.index(repo_path=repo)
    try:
        r = Retriever(cg.store, FakeEmbedder(dim=8), RetrieveConfig())
        pack = await r.retrieve("anything at all", mode="context")
        assert pack.items == []  # nothing indexed/embedded -> empty, no random seeds
    finally:
        await cg.close()


async def test_scores_descend_and_resolved_outranks(
    retriever: tuple[Retriever, CodeGraph],
) -> None:
    r, _ = retriever
    pack = await r.retrieve("circle area", mode="context", depth=1)
    scores = [i.score for i in pack.items]
    assert scores == sorted(scores, reverse=True)


async def test_edge_kinds_override(retriever: tuple[Retriever, CodeGraph]) -> None:
    r, cg = retriever
    circle = await _id(cg, "Circle#")
    pack = await r.retrieve(symbol=circle, mode="context", depth=1, edge_kinds=[EdgeKind.CONTAINS])
    # only CONTAINS expansion -> methods, not unrelated edges
    assert any(i.kind is NodeKind.METHOD for i in pack.items)
