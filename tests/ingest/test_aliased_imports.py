"""BUG-006 aliased imports — an aliased whole-module import (`import pkg.sub as s`)
and a submodule named-import (`from pkg import sub`) bind the local name to the
target *module*, so `s.f()` / `sub.f()` resolve to that module's top-level export.
An aliased import of an external module is not guessed into (ADR-0004)."""

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


async def test_aliased_whole_module_import_resolves(tmp_path: Path) -> None:
    # `import pkg.mathutils as mu` -> `mu.square()` binds to pkg.mathutils.square
    files = {
        "pkg/__init__.py": "",
        "pkg/mathutils.py": "def square(x):\n    return x * x\n",
        "app.py": "import pkg.mathutils as mu\n\n\ndef run():\n    return mu.square(3)\n",
    }
    store = await _resolve(tmp_path, files)
    try:
        assert "square()." in await _calls(store, "run().")
    finally:
        await store.close()


async def test_from_pkg_import_submodule_resolves(tmp_path: Path) -> None:
    # `from pkg import mathutils` -> `mathutils.square()` binds to the submodule
    files = {
        "pkg/__init__.py": "",
        "pkg/mathutils.py": "def square(x):\n    return x * x\n",
        "app.py": "from pkg import mathutils\n\n\ndef run():\n    return mathutils.square(3)\n",
    }
    store = await _resolve(tmp_path, files)
    try:
        assert "square()." in await _calls(store, "run().")
    finally:
        await store.close()


async def test_aliased_external_import_not_guessed(tmp_path: Path) -> None:
    # numpy is external -> `np.square()` must stay unresolved, never guessed onto a
    # same-named local def.
    files = {
        "shadow.py": "def square(x):\n    return x\n",
        "app.py": "import numpy as np\n\n\ndef run():\n    return np.square(3)\n",
    }
    store = await _resolve(tmp_path, files)
    try:
        assert await _calls(store, "run().") == set()
    finally:
        await store.close()
