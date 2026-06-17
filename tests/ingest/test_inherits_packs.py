"""INHERITS edges + inherited-method calls across the OO packs that have a clear
`extends`/`<`/`:` superclass (TS/JS/Java/C#/Ruby/PHP). Rust (trait impls), Go
(embedding), and C++ (method modeling) use different models — follow-ups."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SourceFile
from agentforge_graph.ingest import ImportResolver, PackRegistry, TreeSitterExtractor
from agentforge_graph.ingest.packs import (
    CSHARP_PACK,
    JAVA_PACK,
    JAVASCRIPT_PACK,
    PHP_PACK,
    RUBY_PACK,
    TYPESCRIPT_PACK,
)
from agentforge_graph.store import KuzuGraphStore

_TS = (
    "class Base { helper() { return 1; } }\n"
    "class Sub extends Base { run() { return this.helper(); } }\n"
)
_JS = _TS
_JAVA = (
    "class Base { int helper() { return 1; } }\n"
    "class Sub extends Base { int run() { return this.helper(); } }\n"
)
_CSHARP = (
    "class Base { int helper() { return 1; } }\n"
    "class Sub : Base { int run() { return this.helper(); } }\n"
)
_RUBY = (
    "class Base\n  def helper\n    1\n  end\nend\n"
    "class Sub < Base\n  def run\n    self.helper()\n  end\nend\n"
)
_PHP = (
    "<?php\nclass Base { function helper() { return 1; } }\n"
    "class Sub extends Base { function run() { return $this->helper(); } }\n"
)

_CASES = [
    pytest.param(TYPESCRIPT_PACK, "m.ts", _TS, id="typescript"),
    pytest.param(JAVASCRIPT_PACK, "m.js", _JS, id="javascript"),
    pytest.param(JAVA_PACK, "M.java", _JAVA, id="java"),
    pytest.param(CSHARP_PACK, "M.cs", _CSHARP, id="csharp"),
    pytest.param(RUBY_PACK, "m.rb", _RUBY, id="ruby"),
    pytest.param(PHP_PACK, "m.php", _PHP, id="php"),
]


@pytest.mark.parametrize(("pack", "rel", "source"), _CASES)
async def test_inherits_and_inherited_call(
    tmp_path: Path, pack: object, rel: str, source: str
) -> None:
    store = await KuzuGraphStore.open(tmp_path / "g.kuzu")
    try:
        extractor = TreeSitterExtractor(pack, repo="fixture")  # type: ignore[arg-type]
        sf = SourceFile(
            path=rel,
            text=source,
            language=pack.lang_slug,  # type: ignore[attr-defined]
            content_hash=hashlib.sha256(source.encode()).hexdigest(),
        )
        await store.upsert(extractor.extract(sf))
        await ImportResolver(PackRegistry([pack])).resolve(store)  # type: ignore[list-item]

        nodes = (await store.query(GraphQuery(limit=10000))).nodes
        by = {(n.kind, n.name): n.id for n in nodes}
        sub = by[(NodeKind.CLASS, "Sub")]
        base = by[(NodeKind.CLASS, "Base")]

        # INHERITS edge Sub -> Base
        supers = {e.dst for e in await store.adjacent(sub, [EdgeKind.INHERITS], "out")}
        assert base in supers, "Sub INHERITS Base"

        # inherited call: Sub.run() -> Base.helper() (helper defined on the base)
        run = next(n for n in nodes if n.name == "run")
        helper = next(n for n in nodes if n.name == "helper")
        called = {n.id for n in await store.neighbors(run.id, [EdgeKind.CALLS], depth=1)}
        assert helper.id in called, "this/self.helper() binds to the inherited method"
    finally:
        await store.close()
