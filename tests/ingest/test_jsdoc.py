"""feat-010 follow-up: docstrings beyond Python symbol bodies — JS/TS JSDoc
(`/** … */` before a function/class/method) becomes a DocChunk that DESCRIBES the
symbol it documents (module-level docstrings are a separate follow-up)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SourceFile, SymbolID
from agentforge_graph.ingest import TreeSitterExtractor
from agentforge_graph.ingest.packs.javascript import JAVASCRIPT_PACK
from agentforge_graph.ingest.packs.typescript import TYPESCRIPT_PACK
from agentforge_graph.store import KuzuGraphStore


async def _extract(tmp_path: Path, pack: object, lang: str, text: str) -> KuzuGraphStore:
    store = await KuzuGraphStore.open(tmp_path / "g.kuzu")
    ex = TreeSitterExtractor(pack, repo="fix")  # type: ignore[arg-type]
    sf = SourceFile(
        path=f"m.{lang}",
        text=text,
        language=lang,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    await store.upsert(ex.extract(sf))
    return store


async def _described(store: KuzuGraphStore) -> dict[str, str]:
    """{DocChunk text -> descriptor of the symbol/file it DESCRIBES}."""
    nodes = (await store.query(GraphQuery(kinds=[NodeKind.DOC_CHUNK], limit=999))).nodes
    out: dict[str, str] = {}
    for d in nodes:
        outs = await store.adjacent(d.id, [EdgeKind.DESCRIBES], "out")
        if outs:
            out[str(d.attrs.get("text"))] = SymbolID.parse(outs[0].dst).descriptor
    return out


async def test_js_jsdoc(tmp_path: Path) -> None:
    src = (
        "/** Greets a user. */\n"
        "function greet(name) { return name; }\n\n"
        "/** A widget. */\n"
        "class Widget {\n  /** Renders it. */\n  render() { return 1; }\n}\n"
    )
    store = await _extract(tmp_path, JAVASCRIPT_PACK, "js", src)
    try:
        d = await _described(store)
        assert d.get("Greets a user.") == "greet()."
        assert d.get("A widget.") == "Widget#"
        assert d.get("Renders it.") == "Widget#render()."
    finally:
        await store.close()


async def test_ts_jsdoc(tmp_path: Path) -> None:
    src = "/** Adds two numbers. */\nfunction add(a: number, b: number): number { return a + b; }\n"
    store = await _extract(tmp_path, TYPESCRIPT_PACK, "ts", src)
    try:
        d = await _described(store)
        assert d.get("Adds two numbers.") == "add()."
    finally:
        await store.close()


async def test_jsdoc_multiline_cleaned(tmp_path: Path) -> None:
    src = "/**\n * Line one.\n * Line two.\n */\nfunction f() { return 1; }\n"
    store = await _extract(tmp_path, JAVASCRIPT_PACK, "js", src)
    try:
        d = await _described(store)
        assert "Line one.\nLine two." in d  # markers + per-line `*` stripped
    finally:
        await store.close()


async def test_non_jsdoc_comment_ignored(tmp_path: Path) -> None:
    # a plain `//` or `/* */` (non-`/**`) comment is NOT a docstring
    src = "// just a note\nfunction f() { return 1; }\n/* block */\nfunction g() { return 2; }\n"
    store = await _extract(tmp_path, JAVASCRIPT_PACK, "js", src)
    try:
        nodes = (await store.query(GraphQuery(kinds=[NodeKind.DOC_CHUNK], limit=999))).nodes
        assert nodes == []
    finally:
        await store.close()
