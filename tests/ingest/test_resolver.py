"""ImportResolver (pass 2) over the extracted fixture graph: IMPORTS edges
(internal + external), unique-match CALLS, unresolved recorded-not-guessed,
and idempotency."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, Source, SourceFile, SymbolID
from agentforge_graph.ingest import ImportResolver, PackRegistry, TreeSitterExtractor
from agentforge_graph.ingest.packs.python import PYTHON_PACK
from agentforge_graph.store import KuzuGraphStore


def _sf(path: Path, rel: str) -> SourceFile:
    raw = path.read_bytes()
    return SourceFile(
        path=rel, text=raw.decode(), language="py", content_hash=hashlib.sha256(raw).hexdigest()
    )


@pytest.fixture
async def indexed_store(
    tmp_path: Path, python_repo: Path
) -> AsyncIterator[tuple[KuzuGraphStore, ImportResolver]]:
    store = await KuzuGraphStore.open(tmp_path / "graph.kuzu")
    extractor = TreeSitterExtractor(PYTHON_PACK, repo="fixture")
    for rel in ("mathutils.py", "shapes.py"):
        await store.upsert(extractor.extract(_sf(python_repo / rel, rel)))
    resolver = ImportResolver(PackRegistry([PYTHON_PACK]))
    try:
        yield store, resolver
    finally:
        await store.close()


async def _calls_from(store: KuzuGraphStore, desc: str) -> set[str]:
    """Descriptors reachable from the node with descriptor `desc` over CALLS."""
    nodes = (await store.query(GraphQuery(limit=10000))).nodes
    by_desc = {SymbolID.parse(n.id).descriptor: n.id for n in nodes}
    nbrs = await store.neighbors(by_desc[desc], [EdgeKind.CALLS], depth=1)
    return {SymbolID.parse(n.id).descriptor for n in nbrs}


async def test_resolve_stats(
    indexed_store: tuple[KuzuGraphStore, ImportResolver],
) -> None:
    store, resolver = indexed_store
    stats = await resolver.resolve(store)
    assert stats.imports_resolved == 1  # shapes -> mathutils
    assert stats.imports_external == 1  # shapes -> math
    assert stats.refs_resolved == 2  # cube->square, area->square
    assert stats.refs_unresolved == 1  # describe -> shape.area()


async def test_intra_file_call_edge(
    indexed_store: tuple[KuzuGraphStore, ImportResolver],
) -> None:
    store, resolver = indexed_store
    await resolver.resolve(store)
    assert "square()." in await _calls_from(store, "cube().")


async def test_cross_file_call_edge(
    indexed_store: tuple[KuzuGraphStore, ImportResolver],
) -> None:
    store, resolver = indexed_store
    await resolver.resolve(store)
    # area() calls square, imported from mathutils -> resolves cross-file
    assert "square()." in await _calls_from(store, "Circle#area().")


async def test_external_import_creates_package_node(
    indexed_store: tuple[KuzuGraphStore, ImportResolver],
) -> None:
    store, resolver = indexed_store
    await resolver.resolve(store)
    pkgs = (await store.query(GraphQuery(kinds=[NodeKind.PACKAGE]))).nodes
    assert any(p.name == "math" and p.attrs.get("external") for p in pkgs)


async def test_resolved_edges_have_resolved_provenance(
    indexed_store: tuple[KuzuGraphStore, ImportResolver],
) -> None:
    store, resolver = indexed_store
    await resolver.resolve(store)
    # the math package node + import edges carry source=resolved
    pkgs = (await store.query(GraphQuery(kinds=[NodeKind.PACKAGE]))).nodes
    assert all(p.provenance.source is Source.RESOLVED for p in pkgs)


async def test_resolve_is_idempotent(
    indexed_store: tuple[KuzuGraphStore, ImportResolver],
) -> None:
    store, resolver = indexed_store
    await resolver.resolve(store)
    before = await _calls_from(store, "cube().")
    await resolver.resolve(store)  # second pass must not duplicate
    after = await _calls_from(store, "cube().")
    assert before == after == {"square()."}
