"""BUG-006 qualified bases — `class B extends mod.Base` / `class B(mod.Base)`
resolves to the base class via the importing module alias, emitting an INHERITS
edge and (so) resolving inherited `self.f()`/`this.f()` calls. A qualified base
whose receiver is not an imported module is left unresolved (ADR-0004)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentforge_graph.core import EdgeKind, GraphQuery, SourceFile, SymbolID
from agentforge_graph.ingest import ImportResolver, PackRegistry, TreeSitterExtractor
from agentforge_graph.ingest.packs.javascript import JAVASCRIPT_PACK
from agentforge_graph.ingest.packs.python import PYTHON_PACK
from agentforge_graph.ingest.packs.typescript import TYPESCRIPT_PACK
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


async def _inherits(store: KuzuGraphStore, sub_desc: str) -> set[str]:
    nodes = (await store.query(GraphQuery(limit=10000))).nodes
    by_desc = {SymbolID.parse(n.id).descriptor: n.id for n in nodes}
    nbrs = await store.neighbors(by_desc[sub_desc], [EdgeKind.INHERITS], depth=1)
    return {SymbolID.parse(n.id).descriptor for n in nbrs}


async def _calls(store: KuzuGraphStore, desc: str) -> set[str]:
    nodes = (await store.query(GraphQuery(limit=10000))).nodes
    by_desc = {SymbolID.parse(n.id).descriptor: n.id for n in nodes}
    nbrs = await store.neighbors(by_desc[desc], [EdgeKind.CALLS], depth=1)
    return {SymbolID.parse(n.id).descriptor for n in nbrs}


async def test_python_qualified_base_resolves(tmp_path: Path) -> None:
    files = {
        "base.py": "class Animal:\n    def speak(self):\n        return 'base'\n",
        "dog.py": "import base\n\n\nclass Dog(base.Animal):\n"
        "    def bark(self):\n        return self.speak()\n",
    }
    store = await _resolve(tmp_path, PYTHON_PACK, "py", files)
    try:
        assert "Animal#" in await _inherits(store, "Dog#")
        # inherited `self.speak()` resolves through the qualified-base INHERITS edge
        assert any(c.endswith("speak().") for c in await _calls(store, "Dog#bark()."))
    finally:
        await store.close()


async def test_js_qualified_base_resolves(tmp_path: Path) -> None:
    files = {
        "base.js": "class Animal {\n  speak() { return 'base'; }\n}\n"
        "module.exports = { Animal };\n",
        "dog.js": 'const base = require("./base");\n\n'
        "class Dog extends base.Animal {\n  bark() { return this.speak(); }\n}\n",
    }
    store = await _resolve(tmp_path, JAVASCRIPT_PACK, "js", files)
    try:
        assert "Animal#" in await _inherits(store, "Dog#")
        assert any(c.endswith("speak().") for c in await _calls(store, "Dog#bark()."))
    finally:
        await store.close()


async def test_ts_qualified_base_resolves(tmp_path: Path) -> None:
    files = {
        "base.ts": "export class Animal {\n  speak(): string { return 'base'; }\n}\n",
        "dog.ts": 'import * as base from "./base";\n\n'
        "class Dog extends base.Animal {\n  bark(): string { return this.speak(); }\n}\n",
    }
    store = await _resolve(tmp_path, TYPESCRIPT_PACK, "ts", files)
    try:
        assert "Animal#" in await _inherits(store, "Dog#")
        assert any(c.endswith("speak().") for c in await _calls(store, "Dog#bark()."))
    finally:
        await store.close()


async def test_qualified_base_unknown_receiver_not_guessed(tmp_path: Path) -> None:
    # `notamodule` is never imported -> the qualified base must stay unresolved
    files = {
        "base.py": "class Animal:\n    pass\n",
        "dog.py": "class Dog(notamodule.Animal):\n    pass\n",
    }
    store = await _resolve(tmp_path, PYTHON_PACK, "py", files)
    try:
        assert await _inherits(store, "Dog#") == set()
    finally:
        await store.close()
