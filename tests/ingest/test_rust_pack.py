"""Rust pack: extraction + path-derived module (`use crate::…`) resolution."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SourceFile, SymbolID
from agentforge_graph.core.conformance import ExtractorConformance
from agentforge_graph.ingest import CodeGraph, PackRegistry, TreeSitterExtractor
from agentforge_graph.ingest.packs import BUILTIN_PACKS
from agentforge_graph.ingest.packs.rust import RUST_PACK


def _extractor() -> TreeSitterExtractor:
    return TreeSitterExtractor(RUST_PACK, repo="fixture", commit="c0")


def _sf(text: str, path: str) -> SourceFile:
    return SourceFile(
        path=path, text=text, language="rs", content_hash=hashlib.sha256(text.encode()).hexdigest()
    )


def test_registry_includes_rust() -> None:
    assert RUST_PACK in BUILTIN_PACKS
    reg = PackRegistry(BUILTIN_PACKS)
    assert reg.for_extension(".rs") is RUST_PACK
    assert reg.for_slug("rs") is RUST_PACK


def test_rust_symbol_surface() -> None:
    src = (
        "pub struct Circle { r: f64 }\n"
        "pub enum Color { Red }\n"
        "pub trait Drawable { fn draw(&self); }\n"
        "impl Circle {\n  pub fn new(r: f64) -> Self { Circle { r } }\n"
        "  pub fn area(&self) -> f64 { 1.0 }\n}\n"
        "pub fn compute(x: f64) -> f64 { x }\n"
        "pub const PI: f64 = 3.14;\n"
        "type Meters = f64;\n"
    )
    by_desc = {
        SymbolID.parse(n.id).descriptor: n
        for n in _extractor().extract(_sf(src, "src/geo.rs")).nodes
    }
    assert by_desc["Circle#"].kind is NodeKind.CLASS  # struct (+ impl, merged)
    assert by_desc["Color#"].kind is NodeKind.CLASS  # enum -> Class
    assert by_desc["Drawable#"].kind is NodeKind.INTERFACE  # trait -> Interface
    assert by_desc["Drawable#draw()."].kind is NodeKind.METHOD  # trait method sig
    assert by_desc["Circle#area()."].kind is NodeKind.METHOD  # impl method -> attached to Circle
    assert by_desc["compute()."].kind is NodeKind.FUNCTION
    assert by_desc["PI."].kind is NodeKind.VARIABLE
    assert by_desc["Meters."].kind is NodeKind.TYPE_ALIAS


def test_rust_imports_recorded() -> None:
    src = "use crate::shapes::Shape;\nuse std::collections::HashMap;\n"
    sg = _extractor().extract(_sf(src, "src/geo.rs"))
    file_node = next(n for n in sg.nodes if n.kind is NodeKind.FILE)
    mods = {imp["module"] for imp in file_node.attrs["imports"]}
    assert mods == {"crate::shapes::Shape", "std::collections::HashMap"}


# --- end-to-end resolution --------------------------------------------------


@pytest.fixture
async def rust_repo(tmp_path: Path) -> AsyncIterator[CodeGraph]:
    repo = tmp_path / "proj"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "shapes.rs").write_text(
        "pub struct Shape { pub w: f64 }\npub fn helper() -> f64 { 1.0 }\n"
    )
    (repo / "src" / "geo.rs").write_text(
        "use crate::shapes::Shape;\nuse crate::shapes::helper;\n"
        "use std::fmt::Debug;\npub fn run() -> f64 { helper() }\n"
    )
    (repo / "src" / "lib.rs").write_text("pub mod shapes;\npub mod geo;\n")
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield cg
    finally:
        await cg.close()


async def test_rust_use_crate_resolves_and_binds(rust_repo: CodeGraph) -> None:
    report = rust_repo.stats()
    assert report.resolve.imports_resolved >= 1  # geo -> shapes (use crate::shapes::…)
    assert report.resolve.imports_external >= 1  # std::fmt::Debug
    # `use crate::shapes::helper` binds the item -> cross-file call resolves
    nodes = (await rust_repo.store.graph.query(GraphQuery(limit=10000))).nodes
    run = next(n.id for n in nodes if n.name == "run")
    nbrs = await rust_repo.store.graph.neighbors(run, [EdgeKind.CALLS], depth=1)
    assert "helper" in {n.name for n in nbrs}


# --- conformance ------------------------------------------------------------


class TestRustExtractorConformance(ExtractorConformance):
    @pytest.fixture
    def extractor(self) -> TreeSitterExtractor:
        return TreeSitterExtractor(RUST_PACK, repo="fixture")

    @pytest.fixture
    def sample_file(self) -> SourceFile:
        text = "fn helper() -> i32 { 1 }\nfn f() -> i32 { helper() }\n"
        return _sf(text, "src/a.rs")
