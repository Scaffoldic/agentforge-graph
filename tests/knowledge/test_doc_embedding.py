"""feat-010 follow-up: ADR ``DocChunk`` prose is embedded for semantic search.
A doc-chunk vector hit surfaces the chunk AND seeds its governing ``Decision``
(which then expands to the governed code), so an architectural query reaches the
decision and the code it governs. Doc vectors carry ``source_type: doc``."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import GraphQuery, NodeKind
from agentforge_graph.embed import FakeEmbedder
from agentforge_graph.ingest import CodeGraph

FIXTURES = Path(__file__).parent / "fixtures" / "repo"


@pytest.fixture
async def embedded(tmp_path: Path) -> AsyncIterator[tuple[CodeGraph, FakeEmbedder]]:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    cg = await CodeGraph.index(repo_path=repo)  # also runs the ADR/knowledge pass
    emb = FakeEmbedder(dim=32)
    await cg.embed(embedder=emb)
    try:
        yield cg, emb
    finally:
        await cg.close()


async def _doc_chunks(cg: CodeGraph) -> list[object]:
    return (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.DOC_CHUNK], limit=999))).nodes


async def test_doc_chunks_embedded(tmp_path: Path) -> None:
    # a FRESH index+embed counts the doc chunks (no prior manifest to skip against)
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        docs = await _doc_chunks(cg)
        assert docs  # the fixture ADRs produced doc chunks
        report = await cg.embed(embedder=FakeEmbedder(dim=32))
        assert report.doc_chunks == len(docs)
    finally:
        await cg.close()


async def test_reembed_skips_unchanged_docs(embedded: tuple[CodeGraph, FakeEmbedder]) -> None:
    # the fixture already embedded once → a second unchanged embed skips the doc pass
    cg, _ = embedded
    docs = await _doc_chunks(cg)
    report = await cg.embed(embedder=FakeEmbedder(dim=32))
    assert report.doc_chunks == 0  # incremental: nothing re-embedded
    # but the doc vectors are still present (skip ≠ delete)
    target = next(d for d in docs if d.attrs.get("text"))
    [qvec] = await FakeEmbedder(dim=32).embed(
        [f"{target.attrs.get('heading', '')}\n{target.attrs.get('text', '')}".strip()], "query"
    )
    hits = await cg.store.vectors.search(qvec, k=5)
    assert target.id in {h.ref for h in hits}


async def test_changed_doc_reembeds(tmp_path: Path) -> None:
    # editing an ADR changes the fingerprint → the doc pass runs again
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        await cg.embed(embedder=FakeEmbedder(dim=32))  # first → writes manifest
        adr = next(repo.glob("docs/adr/*.md"))
        adr.write_text(adr.read_text() + "\n\n## New section\n\nMore prose.\n")
        await cg.refresh()
        report = await cg.embed(embedder=FakeEmbedder(dim=32))
        assert report.doc_chunks > 0  # not skipped — a doc changed
    finally:
        await cg.close()


async def test_doc_chunk_vector_is_searchable(embedded: tuple[CodeGraph, FakeEmbedder]) -> None:
    cg, emb = embedded
    docs = await _doc_chunks(cg)
    target = next(d for d in docs if d.attrs.get("text"))
    text = f"{target.attrs.get('heading', '')}\n{target.attrs.get('text', '')}".strip()
    [qvec] = await emb.embed([text], input_type="query")
    hits = await cg.store.vectors.search(qvec, k=5)
    # the exact-text query lands the doc chunk as a hit (FakeEmbedder is determinstic)
    assert target.id in {h.ref for h in hits}


async def test_doc_hit_seeds_governing_decision(embedded: tuple[CodeGraph, FakeEmbedder]) -> None:
    from agentforge_graph.config import RetrieveConfig
    from agentforge_graph.retrieve import Retriever

    cg, emb = embedded
    # query a doc chunk's prose and assert the retrieval surfaces the Decision
    # (seeded from the doc chunk via CONTAINS). Retriever uses the SAME fake
    # embedder the store was embedded with, so the exact-text query is a perfect hit.
    docs = await _doc_chunks(cg)
    target = next(d for d in docs if d.attrs.get("text"))
    text = f"{target.attrs.get('heading', '')}\n{target.attrs.get('text', '')}".strip()
    r = Retriever(cg.store, emb, RetrieveConfig(k=5, depth=2))
    pack = await r.retrieve(text, mode="context")
    kinds = {it.kind for it in pack.items}
    assert NodeKind.DOC_CHUNK in kinds  # the doc chunk itself surfaces
    assert NodeKind.DECISION in kinds  # and its governing decision (seeded)


async def test_no_docs_no_doc_vectors(tmp_path: Path) -> None:
    # a repo with no ADRs → zero doc chunks embedded, report stays at 0
    repo = tmp_path / "bare"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "m.py").write_text("def f():\n    return 1\n")
    cg = await CodeGraph.index(repo_path=repo)
    try:
        report = await cg.embed(embedder=FakeEmbedder(dim=16))
        assert report.doc_chunks == 0
    finally:
        await cg.close()
