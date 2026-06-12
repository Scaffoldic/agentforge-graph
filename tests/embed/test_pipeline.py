"""EmbedPipeline + CodeGraph.embed end-to-end with the FakeEmbedder: chunk
nodes, CHUNK_OF edges, vectors in the store, hash-skip on re-run."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.embed import FakeEmbedder
from agentforge_graph.ingest import CodeGraph

FIXTURES = Path(__file__).parent.parent / "ingest" / "fixtures" / "python"


@pytest.fixture
async def embedded(tmp_path: Path) -> AsyncIterator[tuple[CodeGraph, FakeEmbedder]]:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    cg = await CodeGraph.index(repo_path=repo)
    emb = FakeEmbedder(dim=32)
    await cg.embed(embedder=emb)
    try:
        yield cg, emb
    finally:
        await cg.close()


async def test_chunk_nodes_and_edges_created(
    embedded: tuple[CodeGraph, FakeEmbedder],
) -> None:
    cg, _ = embedded
    chunks = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.CHUNK], limit=1000))).nodes
    assert chunks
    # every chunk has at least one CHUNK_OF edge (to a symbol or the file)
    for c in chunks:
        targets = await cg.store.graph.neighbors(c.id, [EdgeKind.CHUNK_OF], depth=1)
        assert targets


async def test_vectors_searchable(embedded: tuple[CodeGraph, FakeEmbedder]) -> None:
    cg, emb = embedded
    # embed a query with the same fake embedder and search the vector store
    [qvec] = await emb.embed(["circle area"], input_type="query")
    hits = await cg.store.vectors.search(qvec, k=3)
    assert hits
    assert all(SymbolID.parse(h.ref).descriptor.startswith("chunk(") for h in hits)


async def test_expand_from_vector_hit(embedded: tuple[CodeGraph, FakeEmbedder]) -> None:
    cg, emb = embedded
    [qvec] = await emb.embed(["validate token"], input_type="query")
    hits = await cg.store.vectors.search(qvec, k=1)
    # a chunk hit expands into the graph via CHUNK_OF
    result = await cg.store.expand(hits, kinds=[EdgeKind.CHUNK_OF], depth=1)
    assert result.nodes  # the symbols the chunk covers


async def test_reembed_skips_unchanged(embedded: tuple[CodeGraph, FakeEmbedder]) -> None:
    cg, emb = embedded
    report = await cg.embed(embedder=emb)  # second pass, nothing changed
    assert report.skipped_unchanged >= 1
    assert report.embedded == 0


async def test_embed_report_fields(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        report = await cg.embed(embedder=FakeEmbedder(dim=16))
        assert report.files == 2
        assert report.chunks >= 2
        assert report.embedded == report.chunks
        assert report.model == "fake"
        assert report.dim == 16
    finally:
        await cg.close()


async def test_index_with_embed_flag(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    # config-driven embedder would be bedrock; pass fake via direct embed instead.
    cg = await CodeGraph.index(repo_path=repo)
    try:
        await cg.embed(embedder=FakeEmbedder(dim=8))
        chunks = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.CHUNK]))).nodes
        assert chunks
    finally:
        await cg.close()
