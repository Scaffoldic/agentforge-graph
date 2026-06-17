"""BUG-006 — `m.f()` where `m` is an imported module resolves to that module's
top-level export `f` (a unique, safe match). Covers Python `import m` and a JS
default require whose member is a real top-level export. A receiver that is *not*
a module alias is never guessed onto a module-level def (ADR-0004)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentforge_graph.core import EdgeKind, GraphQuery, SourceFile, SymbolID
from agentforge_graph.ingest import ImportResolver, PackRegistry, TreeSitterExtractor
from agentforge_graph.ingest.packs.javascript import JAVASCRIPT_PACK
from agentforge_graph.ingest.packs.python import PYTHON_PACK
from agentforge_graph.store import KuzuGraphStore


async def _resolve(
    tmp_path: Path, pack: object, lang: str, files: dict[str, str]
) -> KuzuGraphStore:
    store = await KuzuGraphStore.open(tmp_path / "g.kuzu")
    extractor = TreeSitterExtractor(pack, repo="fixture")  # type: ignore[arg-type]
    for rel, text in files.items():
        sf = SourceFile(
            path=rel,
            text=text,
            language=lang,
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
        await store.upsert(extractor.extract(sf))
    await ImportResolver(PackRegistry([pack])).resolve(store)  # type: ignore[list-item]
    return store


async def _calls(store: KuzuGraphStore, desc: str) -> set[str]:
    nodes = (await store.query(GraphQuery(limit=10000))).nodes
    by_desc = {SymbolID.parse(n.id).descriptor: n.id for n in nodes}
    nbrs = await store.neighbors(by_desc[desc], [EdgeKind.CALLS], depth=1)
    return {SymbolID.parse(n.id).descriptor for n in nbrs}


async def test_python_module_member_resolves(tmp_path: Path) -> None:
    files = {
        "mathutils.py": "def square(x):\n    return x * x\n",
        "app.py": "import mathutils\n\n\ndef run():\n    return mathutils.square(3)\n",
    }
    store = await _resolve(tmp_path, PYTHON_PACK, "py", files)
    try:
        assert "square()." in await _calls(store, "run().")  # mathutils.square -> square
    finally:
        await store.close()


async def test_python_unknown_receiver_not_guessed(tmp_path: Path) -> None:
    # `obj` is a parameter, not a module → obj.square() must NOT bind to square
    files = {
        "mathutils.py": "def square(x):\n    return x * x\n",
        "app.py": "def run(obj):\n    return obj.square(3)\n",
    }
    store = await _resolve(tmp_path, PYTHON_PACK, "py", files)
    try:
        assert await _calls(store, "run().") == set()
    finally:
        await store.close()


async def test_js_default_require_member_resolves(tmp_path: Path) -> None:
    # utils.js exports a top-level `helper`; `u.helper()` resolves through the alias
    files = {
        "utils.js": "function helper() { return 1; }\nmodule.exports = { helper };\n",
        "app.js": 'const u = require("./utils");\n\nfunction run() { return u.helper(); }\n',
    }
    store = await _resolve(tmp_path, JAVASCRIPT_PACK, "js", files)
    try:
        assert "helper()." in await _calls(store, "run().")
    finally:
        await store.close()
