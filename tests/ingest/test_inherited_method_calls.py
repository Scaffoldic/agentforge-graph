"""BUG-006 — `self.f()` where `f` is defined on a *base* class resolves to the
inherited method (walking INHERITS). Single inheritance + a cross-file base;
ambiguous multi-base definers stay unresolved (ADR-0004 — no MRO guessing)."""

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


async def _calls(store: KuzuGraphStore, desc: str) -> set[str]:
    nodes = (await store.query(GraphQuery(limit=10000))).nodes
    by_desc = {SymbolID.parse(n.id).descriptor: n.id for n in nodes}
    nbrs = await store.neighbors(by_desc[desc], [EdgeKind.CALLS], depth=1)
    return {SymbolID.parse(n.id).descriptor for n in nbrs}


async def test_self_call_resolves_to_inherited_method(tmp_path: Path) -> None:
    src = (
        "class Base:\n"
        "    def helper(self):\n        return 1\n"
        "\n\n"
        "class Sub(Base):\n"
        "    def run(self):\n        return self.helper()\n"  # helper is on Base
    )
    store = await _resolve(tmp_path, {"m.py": src})
    try:
        assert "Base#helper()." in await _calls(store, "Sub#run().")
    finally:
        await store.close()


async def test_inherited_method_across_files(tmp_path: Path) -> None:
    files = {
        "base.py": "class Base:\n    def helper(self):\n        return 1\n",
        "sub.py": (
            "from base import Base\n\n\n"
            "class Sub(Base):\n    def run(self):\n        return self.helper()\n"
        ),
    }
    store = await _resolve(tmp_path, files)
    try:
        assert "Base#helper()." in await _calls(store, "Sub#run().")
    finally:
        await store.close()


async def test_own_method_wins_over_base(tmp_path: Path) -> None:
    src = (
        "class Base:\n    def helper(self):\n        return 1\n"
        "\n\n"
        "class Sub(Base):\n"
        "    def run(self):\n        return self.helper()\n"
        "\n"
        "    def helper(self):\n        return 2\n"  # override on Sub itself
    )
    store = await _resolve(tmp_path, {"m.py": src})
    try:
        assert await _calls(store, "Sub#run().") == {"Sub#helper()."}  # own, not Base's
    finally:
        await store.close()


async def test_ambiguous_multiple_bases_unresolved(tmp_path: Path) -> None:
    # both bases define helper -> not a unique target -> unresolved (no MRO guess)
    src = (
        "class A:\n    def helper(self):\n        return 1\n"
        "\n\n"
        "class B:\n    def helper(self):\n        return 2\n"
        "\n\n"
        "class C(A, B):\n    def run(self):\n        return self.helper()\n"
    )
    store = await _resolve(tmp_path, {"m.py": src})
    try:
        assert await _calls(store, "C#run().") == set()
    finally:
        await store.close()
