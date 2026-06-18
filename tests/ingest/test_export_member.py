"""BUG-006 export-member modeling — assigned-property exports whose value is an
*anonymous* function become Function symbols, so member calls (`m.foo()`), named
destructure requires (`const { foo } = require(...)`) and direct calls resolve.

Covers `exports.foo = fn`, `module.exports.foo = fn`, and inline-function values
in a `module.exports = { foo: fn }` object literal. Non-function assignments
(`exports.x = someVar`) must NOT mint a spurious symbol (ADR-0004)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SourceFile, SymbolID
from agentforge_graph.ingest import ImportResolver, PackRegistry, TreeSitterExtractor
from agentforge_graph.ingest.packs.javascript import JAVASCRIPT_PACK
from agentforge_graph.store import KuzuGraphStore


async def _resolve(tmp_path: Path, files: dict[str, str]) -> KuzuGraphStore:
    store = await KuzuGraphStore.open(tmp_path / "g.kuzu")
    extractor = TreeSitterExtractor(JAVASCRIPT_PACK, repo="fixture")
    for rel, text in files.items():
        sf = SourceFile(
            path=rel,
            text=text,
            language="js",
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
        await store.upsert(extractor.extract(sf))
    await ImportResolver(PackRegistry([JAVASCRIPT_PACK])).resolve(store)
    return store


async def _nodes(store: KuzuGraphStore) -> list[object]:
    return (await store.query(GraphQuery(limit=10000))).nodes


async def _functions(store: KuzuGraphStore) -> set[str]:
    return {n.name for n in await _nodes(store) if n.kind is NodeKind.FUNCTION}


async def _calls(store: KuzuGraphStore, desc: str) -> set[str]:
    by_desc = {SymbolID.parse(n.id).descriptor: n.id for n in await _nodes(store)}
    nbrs = await store.neighbors(by_desc[desc], [EdgeKind.CALLS], depth=1)
    return {SymbolID.parse(n.id).descriptor for n in nbrs}


async def test_exports_dot_property_function_is_a_symbol(tmp_path: Path) -> None:
    files = {
        "utils.js": "exports.helper = function () { return 1; };\n",
        "app.js": 'const u = require("./utils");\n\nfunction run() { return u.helper(); }\n',
    }
    store = await _resolve(tmp_path, files)
    try:
        assert "helper" in await _functions(store)
        assert "helper()." in await _calls(store, "run().")
    finally:
        await store.close()


async def test_exports_dot_property_arrow_is_a_symbol(tmp_path: Path) -> None:
    files = {
        "utils.js": "exports.helper = () => 1;\n",
        "app.js": 'const { helper } = require("./utils");\n\nfunction run() { return helper(); }\n',
    }
    store = await _resolve(tmp_path, files)
    try:
        assert "helper" in await _functions(store)
        # named destructure binds the local `helper` to the export
        assert "helper()." in await _calls(store, "run().")
    finally:
        await store.close()


async def test_module_exports_dot_property_function_is_a_symbol(tmp_path: Path) -> None:
    files = {
        "utils.js": "module.exports.helper = function () { return 1; };\n",
        "app.js": 'const u = require("./utils");\n\nfunction run() { return u.helper(); }\n',
    }
    store = await _resolve(tmp_path, files)
    try:
        assert "helper" in await _functions(store)
        assert "helper()." in await _calls(store, "run().")
    finally:
        await store.close()


async def test_object_literal_inline_functions_are_symbols(tmp_path: Path) -> None:
    files = {
        "utils.js": "module.exports = {\n  add: function (a, b) { return a + b; },\n"
        "  sub: (a, b) => a - b,\n};\n",
        "app.js": 'const u = require("./utils");\n\n'
        "function run() { return u.add(1, 2) + u.sub(3, 1); }\n",
    }
    store = await _resolve(tmp_path, files)
    try:
        fns = await _functions(store)
        assert {"add", "sub"} <= fns
        calls = await _calls(store, "run().")
        assert "add()." in calls
        assert "sub()." in calls
    finally:
        await store.close()


async def test_non_function_assignment_mints_no_symbol(tmp_path: Path) -> None:
    # `exports.x = someVar` is a re-export of an existing binding, not a new
    # function definition — it must not create a spurious Function symbol.
    files = {
        "utils.js": "const internal = 5;\nexports.value = internal;\n",
    }
    store = await _resolve(tmp_path, files)
    try:
        assert "value" not in await _functions(store)
    finally:
        await store.close()
