"""BUG-006 residual — `self.f()` / `this.f()` member calls resolve to the
*enclosing class's* method (a unique, safe match), and a member call on any
other receiver is never guessed onto a same-named module-level def (ADR-0004)."""

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


async def _calls(store: KuzuGraphStore, desc: str) -> set[str]:
    nodes = (await store.query(GraphQuery(limit=10000))).nodes
    by_desc = {SymbolID.parse(n.id).descriptor: n.id for n in nodes}
    nbrs = await store.neighbors(by_desc[desc], [EdgeKind.CALLS], depth=1)
    return {SymbolID.parse(n.id).descriptor for n in nbrs}


# a module-level `handle` decoy that a naive by-name resolver would wrongly bind
_PY = (
    "def handle(x):\n"
    "    return x\n"
    "\n\n"
    "class Service:\n"
    "    def run(self):\n"
    "        return self.handle()\n"  # -> Service#handle, NOT module-level handle
    "\n"
    "    def handle(self):\n"
    "        return 1\n"
    "\n\n"
    "def describe(s):\n"
    "    return s.handle()\n"  # member call on a param -> unresolved (not guessed)
)


async def test_python_self_call_resolves_to_method_not_module(tmp_path: Path) -> None:
    store = await _resolve(tmp_path, PYTHON_PACK, "py", {"svc.py": _PY})
    try:
        run_calls = await _calls(store, "Service#run().")
        assert "Service#handle()." in run_calls  # self.handle() -> the method
        assert "handle()." not in run_calls  # never the module-level decoy
        assert await _calls(store, "describe().") == set()  # s.handle() not guessed
    finally:
        await store.close()


_TS = (
    "export function handle(x: number) { return x; }\n"
    "\n"
    "export class Service {\n"
    "  run() { return this.handle(); }\n"
    "  handle() { return 1; }\n"
    "}\n"
)


async def test_typescript_this_call_resolves_to_method(tmp_path: Path) -> None:
    store = await _resolve(tmp_path, TYPESCRIPT_PACK, "ts", {"svc.ts": _TS})
    try:
        run_calls = await _calls(store, "Service#run().")
        assert "Service#handle()." in run_calls
        assert "handle()." not in run_calls
    finally:
        await store.close()


_JS = (
    "function handle(x) { return x; }\n"
    "\n"
    "class Service {\n"
    "  run() { return this.handle(); }\n"
    "  handle() { return 1; }\n"
    "}\n"
    "module.exports = Service;\n"
)


async def test_javascript_this_call_resolves_to_method(tmp_path: Path) -> None:
    store = await _resolve(tmp_path, JAVASCRIPT_PACK, "js", {"svc.js": _JS})
    try:
        run_calls = await _calls(store, "Service#run().")
        assert "Service#handle()." in run_calls
        assert "handle()." not in run_calls
    finally:
        await store.close()
