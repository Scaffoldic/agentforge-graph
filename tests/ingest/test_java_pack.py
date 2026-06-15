"""Java pack: extraction + namespace/FQN (package + import) resolution."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SourceFile, SymbolID
from agentforge_graph.core.conformance import ExtractorConformance
from agentforge_graph.ingest import CodeGraph, PackRegistry, TreeSitterExtractor
from agentforge_graph.ingest.packs import BUILTIN_PACKS
from agentforge_graph.ingest.packs.java import JAVA_PACK


def _extractor() -> TreeSitterExtractor:
    return TreeSitterExtractor(JAVA_PACK, repo="fixture", commit="c0")


def _sf(text: str, path: str) -> SourceFile:
    return SourceFile(
        path=path,
        text=text,
        language="java",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def test_registry_includes_java() -> None:
    assert JAVA_PACK in BUILTIN_PACKS
    reg = PackRegistry(BUILTIN_PACKS)
    assert reg.for_extension(".java") is JAVA_PACK
    assert reg.for_slug("java") is JAVA_PACK


def test_java_symbol_surface() -> None:
    src = (
        "package com.foo.geo;\nimport com.foo.shapes.Shape;\n\n"
        "public interface Drawable { void draw(); }\n"
        "public class Circle extends Shape implements Drawable {\n"
        "    public Circle(double r) {}\n"
        "    public double area() { return 1.0; }\n"
        "}\n"
        "enum Color { RED }\n"
        "record Point(int x, int y) {}\n"
    )
    sg = _extractor().extract(_sf(src, "src/main/java/com/foo/geo/Circle.java"))
    by_desc = {SymbolID.parse(n.id).descriptor: n for n in sg.nodes}
    assert by_desc["Drawable#"].kind is NodeKind.INTERFACE
    assert by_desc["Circle#"].kind is NodeKind.CLASS
    assert by_desc["Circle#area()."].kind is NodeKind.METHOD  # method nested in class
    assert by_desc["Circle#Circle()."].kind is NodeKind.METHOD  # constructor
    assert by_desc["Color#"].kind is NodeKind.CLASS  # enum -> Class
    assert by_desc["Point#"].kind is NodeKind.CLASS  # record -> Class
    file_node = next(n for n in sg.nodes if n.kind is NodeKind.FILE)
    assert file_node.attrs["namespace"] == "com.foo.geo"
    assert file_node.attrs["imports"][0]["module"] == "com.foo.shapes.Shape"


# --- end-to-end resolution --------------------------------------------------


@pytest.fixture
async def java_repo(tmp_path: Path) -> AsyncIterator[CodeGraph]:
    repo = tmp_path / "proj"
    base = repo / "src" / "main" / "java" / "com" / "foo"
    (base / "shapes").mkdir(parents=True)
    (base / "geo").mkdir(parents=True)
    (base / "shapes" / "Shape.java").write_text("package com.foo.shapes;\npublic class Shape {}\n")
    (base / "geo" / "Circle.java").write_text(
        "package com.foo.geo;\nimport com.foo.shapes.Shape;\nimport java.util.List;\n"
        "public class Circle extends Shape {}\n"
    )
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield cg
    finally:
        await cg.close()


async def test_java_import_fqn_resolves_across_source_root(java_repo: CodeGraph) -> None:
    report = java_repo.stats()
    # resolution is by the `package` declaration, so the src/main/java root is irrelevant
    assert report.resolve.imports_resolved >= 1  # com.foo.geo.Circle -> com.foo.shapes.Shape
    assert report.resolve.imports_external >= 1  # java.util.List
    nodes = (await java_repo.store.graph.query(GraphQuery(limit=10000))).nodes
    circle = next(
        n.id
        for n in nodes
        if SymbolID.parse(n.id).path.endswith("geo/Circle.java") and n.kind is NodeKind.FILE
    )
    imps = await java_repo.store.graph.neighbors(circle, [EdgeKind.IMPORTS], depth=1)
    in_repo = {SymbolID.parse(n.id).path for n in imps if n.kind is NodeKind.FILE}
    assert any(p.endswith("shapes/Shape.java") for p in in_repo)


# --- conformance ------------------------------------------------------------


class TestJavaExtractorConformance(ExtractorConformance):
    @pytest.fixture
    def extractor(self) -> TreeSitterExtractor:
        return TreeSitterExtractor(JAVA_PACK, repo="fixture")

    @pytest.fixture
    def sample_file(self) -> SourceFile:
        text = "class A {\n  int helper() { return 1; }\n  int f() { return helper(); }\n}\n"
        return _sf(text, "A.java")
