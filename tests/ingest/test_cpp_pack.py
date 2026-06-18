"""C++ pack (Tier B): extraction + quoted #include resolution."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SourceFile, SymbolID
from agentforge_graph.core.conformance import ExtractorConformance
from agentforge_graph.ingest import CodeGraph, PackRegistry, TreeSitterExtractor
from agentforge_graph.ingest.packs import BUILTIN_PACKS
from agentforge_graph.ingest.packs.cpp import CPP_PACK


def _extractor() -> TreeSitterExtractor:
    return TreeSitterExtractor(CPP_PACK, repo="fixture", commit="c0")


def _sf(text: str, path: str) -> SourceFile:
    return SourceFile(
        path=path, text=text, language="cpp", content_hash=hashlib.sha256(text.encode()).hexdigest()
    )


def test_registry_includes_cpp() -> None:
    assert CPP_PACK in BUILTIN_PACKS
    reg = PackRegistry(BUILTIN_PACKS)
    assert reg.for_extension(".cpp") is CPP_PACK
    assert reg.for_extension(".hpp") is CPP_PACK
    assert reg.for_slug("cpp") is CPP_PACK


def test_cpp_symbol_surface() -> None:
    src = (
        '#include "geo/shape.h"\n#include <vector>\n'
        "namespace geo {\n"
        "class Circle : public Shape {\npublic:\n  Circle(double r);\n  double area() const;\n};\n"
        "struct Point { int x; };\n"
        "enum Color { RED };\n"
        "double compute(double x) { return x; }\n"
        "}\n"
        "void freefn() { compute(1); }\n"
    )
    sg = _extractor().extract(_sf(src, "circle.cpp"))
    by_desc = {SymbolID.parse(n.id).descriptor: n for n in sg.nodes}
    assert by_desc["Circle#"].kind is NodeKind.CLASS
    assert by_desc["Circle#area()."].kind is NodeKind.METHOD  # in-class method decl
    assert by_desc["Circle#Circle()."].kind is NodeKind.METHOD  # constructor
    assert by_desc["Point#"].kind is NodeKind.CLASS  # struct -> Class
    assert by_desc["Color#"].kind is NodeKind.CLASS  # enum -> Class
    assert by_desc["compute()."].kind is NodeKind.FUNCTION  # free fn (namespace not a scope def)
    assert by_desc["freefn()."].kind is NodeKind.FUNCTION
    # quoted include captured; <vector> (system) skipped
    file_node = next(n for n in sg.nodes if n.kind is NodeKind.FILE)
    assert {i["module"] for i in file_node.attrs["imports"]} == {"geo/shape.h"}


def test_cpp_inline_methods_are_symbols() -> None:
    # inline method *definitions* (with a body, in the class) become METHOD symbols
    src = (
        "struct Circle {\n"
        "  double r;\n"
        "  double area() const { return r * r; }\n"
        "  double scaled() const { return this->area() * 2; }\n"
        "};\n"
    )
    sg = _extractor().extract(_sf(src, "circle.cpp"))
    by_desc = {SymbolID.parse(n.id).descriptor: n for n in sg.nodes}
    assert by_desc["Circle#area()."].kind is NodeKind.METHOD
    assert by_desc["Circle#scaled()."].kind is NodeKind.METHOD


async def test_cpp_this_call_resolves_to_enclosing_method(tmp_path: Path) -> None:
    # `this->area()` inside `scaled()` binds to the enclosing class's `area`;
    # a call on any other receiver is left unresolved (ADR-0004).
    from agentforge_graph.ingest import ImportResolver
    from agentforge_graph.store import KuzuGraphStore

    src = (
        "struct Circle {\n"
        "  double r;\n"
        "  double area() const { return r * r; }\n"
        "  double scaled() const { return this->area() * 2; }\n"
        "  void grow(Circle& other) { other.area(); }\n"
        "};\n"
    )
    store = await KuzuGraphStore.open(tmp_path / "g.kuzu")
    try:
        await store.upsert(_extractor().extract(_sf(src, "circle.cpp")))
        await ImportResolver(PackRegistry([CPP_PACK])).resolve(store)
        nodes = (await store.query(GraphQuery(limit=10000))).nodes
        by_desc = {SymbolID.parse(n.id).descriptor: n.id for n in nodes}
        # this->area() inside scaled() resolves to Circle#area
        scaled_calls = await store.neighbors(by_desc["Circle#scaled()."], [EdgeKind.CALLS], depth=1)
        assert "Circle#area()." in {SymbolID.parse(n.id).descriptor for n in scaled_calls}
        # other.area() on a non-this receiver stays unresolved (no CALLS edge)
        grow_calls = await store.neighbors(by_desc["Circle#grow()."], [EdgeKind.CALLS], depth=1)
        assert grow_calls == []
    finally:
        await store.close()


# --- end-to-end resolution --------------------------------------------------


@pytest.fixture
async def cpp_repo(tmp_path: Path) -> AsyncIterator[CodeGraph]:
    repo = tmp_path / "proj"
    (repo / "geo").mkdir(parents=True)
    (repo / "geo" / "shape.h").write_text("struct Shape { double base(); };\n")
    (repo / "main.cpp").write_text('#include "geo/shape.h"\nint main() { return 0; }\n')
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield cg
    finally:
        await cg.close()


async def test_cpp_quoted_include_resolves(cpp_repo: CodeGraph) -> None:
    report = cpp_repo.stats()
    assert report.resolve.imports_resolved >= 1  # main.cpp -> geo/shape.h
    nodes = (await cpp_repo.store.graph.query(GraphQuery(limit=10000))).nodes
    main_file = next(
        n.id for n in nodes if SymbolID.parse(n.id).path == "main.cpp" and n.kind is NodeKind.FILE
    )
    imps = await cpp_repo.store.graph.neighbors(main_file, [EdgeKind.IMPORTS], depth=1)
    in_repo = {SymbolID.parse(n.id).path for n in imps if n.kind is NodeKind.FILE}
    assert "geo/shape.h" in in_repo


# --- conformance ------------------------------------------------------------


class TestCppExtractorConformance(ExtractorConformance):
    @pytest.fixture
    def extractor(self) -> TreeSitterExtractor:
        return TreeSitterExtractor(CPP_PACK, repo="fixture")

    @pytest.fixture
    def sample_file(self) -> SourceFile:
        text = "int helper() { return 1; }\nint f() { return helper(); }\n"
        return _sf(text, "a.cpp")
