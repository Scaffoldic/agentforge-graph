"""C# pack: extraction + namespace-prefix (`using`) resolution."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SourceFile, SymbolID
from agentforge_graph.core.conformance import ExtractorConformance
from agentforge_graph.ingest import CodeGraph, PackRegistry, TreeSitterExtractor
from agentforge_graph.ingest.packs import BUILTIN_PACKS
from agentforge_graph.ingest.packs.csharp import CSHARP_PACK


def _extractor() -> TreeSitterExtractor:
    return TreeSitterExtractor(CSHARP_PACK, repo="fixture", commit="c0")


def _sf(text: str, path: str) -> SourceFile:
    return SourceFile(
        path=path, text=text, language="cs", content_hash=hashlib.sha256(text.encode()).hexdigest()
    )


def test_registry_includes_csharp() -> None:
    assert CSHARP_PACK in BUILTIN_PACKS
    reg = PackRegistry(BUILTIN_PACKS)
    assert reg.for_extension(".cs") is CSHARP_PACK
    assert reg.for_slug("cs") is CSHARP_PACK


def test_csharp_symbol_surface() -> None:
    src = (
        "using System;\nusing App.Shapes;\n"
        "namespace App.Geo {\n"
        "  public interface IDrawable { void Draw(); }\n"
        "  public class Circle : Shape { public Circle(){} public double Area()=>1.0; }\n"
        "  public struct Point { public int X; }\n"
        "  public enum Color { Red }\n"
        "  public record Vec(int X);\n"
        "}\n"
    )
    sg = _extractor().extract(_sf(src, "src/Geo/Circle.cs"))
    by_desc = {SymbolID.parse(n.id).descriptor: n for n in sg.nodes}
    assert by_desc["IDrawable#"].kind is NodeKind.INTERFACE
    assert by_desc["Circle#"].kind is NodeKind.CLASS
    assert by_desc["Circle#Area()."].kind is NodeKind.METHOD
    assert by_desc["Point#"].kind is NodeKind.CLASS  # struct -> Class
    assert by_desc["Color#"].kind is NodeKind.CLASS  # enum -> Class
    assert by_desc["Vec#"].kind is NodeKind.CLASS  # record -> Class
    file_node = next(n for n in sg.nodes if n.kind is NodeKind.FILE)
    assert file_node.attrs["namespace"] == "App.Geo"
    assert {i["module"] for i in file_node.attrs["imports"]} == {"System", "App.Shapes"}


# --- end-to-end resolution --------------------------------------------------


@pytest.fixture
async def cs_repo(tmp_path: Path) -> AsyncIterator[CodeGraph]:
    repo = tmp_path / "proj"
    (repo / "Shapes").mkdir(parents=True)
    (repo / "Geo").mkdir(parents=True)
    (repo / "Shapes" / "Shape.cs").write_text(
        "namespace App.Shapes;\npublic class Shape {}\npublic class Box {}\n"
    )
    (repo / "Geo" / "Circle.cs").write_text(
        "using System;\nusing App.Shapes;\nnamespace App.Geo;\npublic class Circle : Shape {}\n"
    )
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield cg
    finally:
        await cg.close()


async def test_csharp_using_resolves_namespace_to_files(cs_repo: CodeGraph) -> None:
    report = cs_repo.stats()
    # `using App.Shapes` -> the in-repo file declaring that namespace; `using System` -> external
    assert report.resolve.imports_resolved >= 1
    assert report.resolve.imports_external >= 1
    nodes = (await cs_repo.store.graph.query(GraphQuery(limit=10000))).nodes
    circle = next(
        n.id
        for n in nodes
        if SymbolID.parse(n.id).path == "Geo/Circle.cs" and n.kind is NodeKind.FILE
    )
    imps = await cs_repo.store.graph.neighbors(circle, [EdgeKind.IMPORTS], depth=1)
    in_repo = {SymbolID.parse(n.id).path for n in imps if n.kind is NodeKind.FILE}
    assert "Shapes/Shape.cs" in in_repo


# --- conformance ------------------------------------------------------------


class TestCSharpExtractorConformance(ExtractorConformance):
    @pytest.fixture
    def extractor(self) -> TreeSitterExtractor:
        return TreeSitterExtractor(CSHARP_PACK, repo="fixture")

    @pytest.fixture
    def sample_file(self) -> SourceFile:
        text = "class A {\n  int Helper() => 1;\n  int F() { return Helper(); }\n}\n"
        return _sf(text, "A.cs")
