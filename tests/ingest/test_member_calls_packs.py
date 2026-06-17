"""BUG-006 — `self`/`this`/`$this` member calls resolve to the enclosing class's
method across the keyword-receiver packs (Java/C#/Rust/Ruby/PHP). Go (receiver is
a named variable) and C++ (inline struct methods aren't modeled as symbols yet)
are tracked follow-ups."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SourceFile, SymbolID
from agentforge_graph.ingest import ImportResolver, PackRegistry, TreeSitterExtractor
from agentforge_graph.ingest.packs import (
    CSHARP_PACK,
    JAVA_PACK,
    PHP_PACK,
    RUBY_PACK,
    RUST_PACK,
)
from agentforge_graph.store import KuzuGraphStore

_JAVA = """
class Service {
  int run() { return this.handle(); }
  int handle() { return 1; }
}
"""
_CSHARP = """
class Service {
  int run() { return this.handle(); }
  int handle() { return 1; }
}
"""
_RUST = """
fn handle() -> i32 { 0 }
struct Service;
impl Service {
  fn run(&self) -> i32 { self.handle() }
  fn handle(&self) -> i32 { 1 }
}
"""
_RUBY = """
def handle
  0
end
class Service
  def run
    self.handle()
  end
  def handle
    1
  end
end
"""
_PHP = """<?php
function handle() { return 0; }
class Service {
  function run() { return $this->handle(); }
  function handle() { return 1; }
}
"""
_CASES = [
    pytest.param(JAVA_PACK, "Service.java", _JAVA, id="java"),
    pytest.param(CSHARP_PACK, "Service.cs", _CSHARP, id="csharp"),
    pytest.param(RUST_PACK, "service.rs", _RUST, id="rust"),
    pytest.param(RUBY_PACK, "service.rb", _RUBY, id="ruby"),
    pytest.param(PHP_PACK, "service.php", _PHP, id="php"),
]


@pytest.mark.parametrize(("pack", "rel", "source"), _CASES)
async def test_self_call_resolves_to_enclosing_method(
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
        cls = next(n for n in nodes if n.kind is NodeKind.CLASS and n.name == "Service")
        methods = await store.neighbors(cls.id, [EdgeKind.CONTAINS], depth=1)
        run = next(m for m in methods if m.name == "run")
        handle_in_class = next(m for m in methods if m.name == "handle")

        called = {n.id for n in await store.neighbors(run.id, [EdgeKind.CALLS], depth=1)}
        assert handle_in_class.id in called, "self/this call must bind to the class method"
        # precision: never the same-named top-level decoy (where the language has one)
        outside = [
            n.id for n in nodes if n.name == "handle" and n.id not in {m.id for m in methods}
        ]
        assert all(o not in called for o in outside), "must not bind to a module-level decoy"
        assert SymbolID.parse(run.id)  # ids well-formed
    finally:
        await store.close()
