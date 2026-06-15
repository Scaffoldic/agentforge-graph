"""PHP pack: extraction + namespace/FQN import resolution."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SourceFile, SymbolID
from agentforge_graph.core.conformance import ExtractorConformance
from agentforge_graph.ingest import CodeGraph, PackRegistry, TreeSitterExtractor
from agentforge_graph.ingest.packs import BUILTIN_PACKS
from agentforge_graph.ingest.packs.php import PHP_PACK


def _extractor() -> TreeSitterExtractor:
    return TreeSitterExtractor(PHP_PACK, repo="fixture", commit="c0")


def _sf(text: str, path: str) -> SourceFile:
    return SourceFile(
        path=path, text=text, language="php", content_hash=hashlib.sha256(text.encode()).hexdigest()
    )


def test_registry_includes_php() -> None:
    assert PHP_PACK in BUILTIN_PACKS
    reg = PackRegistry(BUILTIN_PACKS)
    assert reg.for_extension(".php") is PHP_PACK
    assert reg.for_slug("php") is PHP_PACK


def test_php_symbol_surface() -> None:
    src = (
        "<?php\nnamespace App\\Geo;\nuse App\\Shapes\\Shape;\n\n"
        "interface Drawable { public function draw(): void; }\n"
        "class Circle extends Shape { public function area(): float { return 1.0; } }\n"
        "trait Loggable { public function log(): void {} }\n"
        "enum Color { case Red; }\n"
        "function compute(float $x): float { return $x; }\n"
        "const PI = 3.14;\n"
    )
    sg = _extractor().extract(_sf(src, "src/Geo/Circle.php"))
    by_desc = {SymbolID.parse(n.id).descriptor: n for n in sg.nodes}
    assert by_desc["Drawable#"].kind is NodeKind.INTERFACE
    assert by_desc["Circle#"].kind is NodeKind.CLASS
    assert by_desc["Circle#area()."].kind is NodeKind.METHOD  # method nested in class
    assert by_desc["Loggable#"].kind is NodeKind.CLASS  # trait -> Class
    assert by_desc["Color#"].kind is NodeKind.CLASS  # enum -> Class
    assert by_desc["compute()."].kind is NodeKind.FUNCTION
    assert by_desc["PI."].kind is NodeKind.VARIABLE
    # the namespace declaration is recorded for FQN resolution
    file_node = next(n for n in sg.nodes if n.kind is NodeKind.FILE)
    assert file_node.attrs["namespace"] == "App\\Geo"
    assert file_node.attrs["imports"][0]["module"] == "App\\Shapes\\Shape"


# --- end-to-end resolution --------------------------------------------------


@pytest.fixture
async def php_repo(tmp_path: Path) -> AsyncIterator[CodeGraph]:
    repo = tmp_path / "proj"
    (repo / "src" / "Shapes").mkdir(parents=True)
    (repo / "src" / "Geo").mkdir(parents=True)
    (repo / "src" / "Shapes" / "Shape.php").write_text(
        "<?php\nnamespace App\\Shapes;\nclass Shape {}\n"
    )
    (repo / "src" / "Geo" / "Circle.php").write_text(
        "<?php\nnamespace App\\Geo;\nuse App\\Shapes\\Shape;\nuse Psr\\Log\\LoggerInterface;\n"
        "class Circle extends Shape {}\n"
    )
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield cg
    finally:
        await cg.close()


async def test_php_fqn_use_resolves_in_repo(php_repo: CodeGraph) -> None:
    report = php_repo.stats()
    assert report.resolve.imports_resolved >= 1  # App\Geo\Circle -> App\Shapes\Shape
    assert report.resolve.imports_external >= 1  # Psr\Log\LoggerInterface (not in repo)
    nodes = (await php_repo.store.graph.query(GraphQuery(limit=10000))).nodes
    circle = next(
        n.id
        for n in nodes
        if SymbolID.parse(n.id).path == "src/Geo/Circle.php" and n.kind is NodeKind.FILE
    )
    imps = await php_repo.store.graph.neighbors(circle, [EdgeKind.IMPORTS], depth=1)
    in_repo = {SymbolID.parse(n.id).path for n in imps if n.kind is NodeKind.FILE}
    assert "src/Shapes/Shape.php" in in_repo


# --- conformance ------------------------------------------------------------


class TestPhpExtractorConformance(ExtractorConformance):
    @pytest.fixture
    def extractor(self) -> TreeSitterExtractor:
        return TreeSitterExtractor(PHP_PACK, repo="fixture")

    @pytest.fixture
    def sample_file(self) -> SourceFile:
        text = "<?php\nfunction helper() { return 1; }\nfunction f() { return helper(); }\n"
        return _sf(text, "a.php")
