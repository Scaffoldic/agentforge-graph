"""Run feat-003's VectorStoreConformance against the LanceDB adapter, plus
a few adapter internals (empty upsert, search-before-table, unfilterable
column rejection)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core.conformance import VectorStoreConformance, make_sample_embeddings
from agentforge_graph.store import LanceVectorStore


@pytest.fixture
async def vectors(tmp_path: Path) -> AsyncIterator[LanceVectorStore]:
    v = await LanceVectorStore.open(tmp_path / "vectors.lance")
    try:
        yield v
    finally:
        await v.close()


class TestLanceVectorStore(VectorStoreConformance):
    @pytest.fixture
    async def vectors(self, tmp_path: Path) -> AsyncIterator[LanceVectorStore]:
        v = await LanceVectorStore.open(tmp_path / "vectors.lance")
        try:
            yield v
        finally:
            await v.close()


async def test_empty_upsert_is_noop(vectors: LanceVectorStore) -> None:
    await vectors.upsert([])
    assert await vectors.search([0.0] * 8, k=5) == []


async def test_search_before_any_table(vectors: LanceVectorStore) -> None:
    # no table created yet → empty result, not an error
    assert await vectors.search([1.0] * 8, k=3) == []


async def test_delete_where_before_table(vectors: LanceVectorStore) -> None:
    await vectors.delete_where({"kind": "Chunk"})  # no-op, no error


async def test_path_filter_and_attrs_round_trip(vectors: LanceVectorStore) -> None:
    items = make_sample_embeddings()
    await vectors.upsert(items)
    hits = await vectors.search(items[0].vector, k=10, filter={"ref": items[0].ref})
    assert [h.ref for h in hits] == [items[0].ref]
    assert hits[0].attrs == {"ordinal": 0}


async def test_search_score_is_cosine_similarity(vectors: LanceVectorStore) -> None:
    # BUG-002: scores are a cosine similarity in [0, 1] (higher = closer), not a
    # negative distance — an identical vector scores ~1.0.
    items = make_sample_embeddings()  # orthogonal one-hot vectors
    await vectors.upsert(items)
    hits = await vectors.search(items[1].vector, k=3)
    assert hits[0].ref == items[1].ref
    assert hits[0].score == pytest.approx(1.0, abs=1e-3)  # identical → similarity 1
    assert all(0.0 <= h.score <= 1.0 for h in hits)
    assert all(hits[i].score >= hits[i + 1].score for i in range(len(hits) - 1))


async def test_unfilterable_column_rejected(vectors: LanceVectorStore) -> None:
    await vectors.upsert(make_sample_embeddings())
    with pytest.raises(ValueError, match="unfilterable"):
        await vectors.delete_where({"ordinal": 0})


async def test_close_is_idempotent(vectors: LanceVectorStore) -> None:
    await vectors.close()
    await vectors.close()


async def test_vectors_persist_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "vectors.lance"
    items = make_sample_embeddings()
    v1 = await LanceVectorStore.open(path)
    await v1.upsert(items)
    await v1.close()
    v2 = await LanceVectorStore.open(path)  # fresh handle: must find the table
    try:
        hits = await v2.search(items[0].vector, k=1)
        assert hits and hits[0].ref == items[0].ref
    finally:
        await v2.close()
