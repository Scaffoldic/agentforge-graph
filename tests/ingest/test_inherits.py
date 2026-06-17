"""INHERITS edges (feat-002 gap): a class's base classes resolve to in-repo
class nodes. Same-file and cross-file (imported base); an external/by-name-only
base stays unresolved (ADR-0004 — never guessed)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentforge_graph.core import EdgeKind, GraphQuery, SourceFile, SymbolID
from agentforge_graph.ingest import ImportResolver, PackRegistry, TreeSitterExtractor
from agentforge_graph.ingest.packs.python import PYTHON_PACK
from agentforge_graph.store import KuzuGraphStore


async def _resolve(tmp_path: Path, files: dict[str, str]) -> KuzuGraphStore:
    store = await KuzuGraphStore.open(tmp_path / "g.kuzu")
    extractor = TreeSitterExtractor(PYTHON_PACK, repo="fixture")
    for rel, text in files.items():
        sf = SourceFile(
            path=rel,
            text=text,
            language="py",
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
        await store.upsert(extractor.extract(sf))
    await ImportResolver(PackRegistry([PYTHON_PACK])).resolve(store)
    return store


async def _supers(store: KuzuGraphStore, desc: str) -> set[str]:
    nodes = (await store.query(GraphQuery(limit=10000))).nodes
    by_desc = {SymbolID.parse(n.id).descriptor: n.id for n in nodes}
    edges = await store.adjacent(by_desc[desc], [EdgeKind.INHERITS], "out")
    return {SymbolID.parse(e.dst).descriptor for e in edges}


async def test_same_file_inheritance(tmp_path: Path) -> None:
    store = await _resolve(tmp_path, {"m.py": "class A:\n    pass\n\n\nclass B(A):\n    pass\n"})
    try:
        assert await _supers(store, "B#") == {"A#"}
        assert await _supers(store, "A#") == set()
    finally:
        await store.close()


async def test_cross_file_inheritance(tmp_path: Path) -> None:
    files = {
        "base.py": "class Base:\n    pass\n",
        "impl.py": "from base import Base\n\n\nclass Impl(Base):\n    pass\n",
    }
    store = await _resolve(tmp_path, files)
    try:
        assert await _supers(store, "Impl#") == {"Base#"}  # imported base resolves
    finally:
        await store.close()


async def test_external_base_not_guessed(tmp_path: Path) -> None:
    # base is from an external package -> no in-repo class -> no INHERITS edge
    files = {"m.py": "from django.db import models\n\n\nclass Post(models):\n    pass\n"}
    store = await _resolve(tmp_path, files)
    try:
        assert await _supers(store, "Post#") == set()
    finally:
        await store.close()


async def test_inherits_is_idempotent(tmp_path: Path) -> None:
    store = await _resolve(tmp_path, {"m.py": "class A:\n    pass\n\n\nclass B(A):\n    pass\n"})
    try:
        await ImportResolver(PackRegistry([PYTHON_PACK])).resolve(store)  # second pass
        assert await _supers(store, "B#") == {"A#"}  # no duplicate edge
    finally:
        await store.close()
