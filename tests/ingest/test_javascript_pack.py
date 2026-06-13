"""JavaScript pack: extraction, relative-import resolution, end-to-end CALLS.

Shares the TS grammar family; the only structural delta is the class-name
node ((identifier) vs (type_identifier)). These tests mirror the TS pack to
prove the JS pack behaves identically over the same harness.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, Source, SourceFile, SymbolID
from agentforge_graph.core.conformance import ExtractorConformance
from agentforge_graph.ingest import CodeGraph, PackRegistry, TreeSitterExtractor
from agentforge_graph.ingest.packs import BUILTIN_PACKS
from agentforge_graph.ingest.packs.javascript import JAVASCRIPT_PACK

FIXTURES = Path(__file__).parent / "fixtures" / "javascript"


def _sf(path: Path, rel: str) -> SourceFile:
    raw = path.read_bytes()
    return SourceFile(
        path=rel, text=raw.decode(), language="js", content_hash=hashlib.sha256(raw).hexdigest()
    )


def _extractor() -> TreeSitterExtractor:
    return TreeSitterExtractor(JAVASCRIPT_PACK, repo="fixture", commit="c0")


# --- pack module resolution -------------------------------------------------


def test_js_module_path_is_relative_style() -> None:
    assert JAVASCRIPT_PACK.module_path("mathutils.js") == "mathutils"
    assert JAVASCRIPT_PACK.module_path("a/b/c.js") == "a/b/c"  # not dotted


def test_js_resolve_import() -> None:
    assert JAVASCRIPT_PACK.resolve_import("shapes.js", "./mathutils") == "mathutils"
    assert JAVASCRIPT_PACK.resolve_import("a/b.js", "../util/x") == "util/x"
    assert JAVASCRIPT_PACK.resolve_import("a/b.js", "react") == "react"  # external, unchanged


def test_registry_includes_javascript() -> None:
    assert JAVASCRIPT_PACK in BUILTIN_PACKS
    reg = PackRegistry(BUILTIN_PACKS)
    assert reg.for_extension(".js") is JAVASCRIPT_PACK
    assert reg.for_extension(".jsx") is JAVASCRIPT_PACK
    assert reg.for_extension(".mjs") is JAVASCRIPT_PACK
    assert reg.for_slug("js") is JAVASCRIPT_PACK


# --- extraction -------------------------------------------------------------


def test_js_nodes_descriptors_and_method_promotion() -> None:
    sg = _extractor().extract(_sf(FIXTURES / "shapes.js", "shapes.js"))
    by_desc = {SymbolID.parse(n.id).descriptor: n for n in sg.nodes}
    assert by_desc["Circle#"].kind is NodeKind.CLASS
    assert by_desc["Circle#area()."].kind is NodeKind.METHOD  # promoted (nested in class)
    assert by_desc["Circle#constructor()."].kind is NodeKind.METHOD
    assert by_desc["describe()."].kind is NodeKind.FUNCTION  # top-level


def test_js_imports_and_refs_recorded() -> None:
    sg = _extractor().extract(_sf(FIXTURES / "shapes.js", "shapes.js"))
    file_node = next(n for n in sg.nodes if n.kind is NodeKind.FILE)
    imp = file_node.attrs["imports"][0]
    assert imp["module"] == "./mathutils"
    assert "square" in imp["names"]
    by_desc = {SymbolID.parse(n.id).descriptor: n for n in sg.nodes}
    assert "square" in {r["name"] for r in by_desc["Circle#area()."].attrs.get("refs", [])}


def test_js_signature_captured() -> None:
    sg = _extractor().extract(_sf(FIXTURES / "mathutils.js", "mathutils.js"))
    by_desc = {SymbolID.parse(n.id).descriptor: n for n in sg.nodes}
    assert by_desc["square()."].attrs["signature"].startswith("function square")


# --- end-to-end resolution --------------------------------------------------


@pytest.fixture
async def js_graph(tmp_path: Path) -> AsyncIterator[CodeGraph]:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield cg
    finally:
        await cg.close()


async def _calls_from(cg: CodeGraph, desc: str) -> set[str]:
    nodes = (await cg.store.graph.query(GraphQuery(limit=10000))).nodes
    sid = next(n.id for n in nodes if SymbolID.parse(n.id).descriptor == desc)
    nbrs = await cg.store.graph.neighbors(sid, [EdgeKind.CALLS], depth=1)
    return {SymbolID.parse(n.id).descriptor for n in nbrs}


async def test_js_index_report(js_graph: CodeGraph) -> None:
    report = js_graph.stats()
    assert report.files_indexed == 2
    assert report.by_node_kind.get("Class") == 1
    assert report.by_node_kind.get("Method") == 2  # constructor, area
    assert report.resolve.refs_resolved == 2  # cube->square, area->square
    assert report.resolve.imports_resolved == 1  # shapes -> mathutils (relative)


async def test_js_intra_file_call(js_graph: CodeGraph) -> None:
    assert "square()." in await _calls_from(js_graph, "cube().")


async def test_js_cross_file_call_via_relative_import(js_graph: CodeGraph) -> None:
    # area() calls square, imported via "./mathutils" -> resolves cross-file
    assert "square()." in await _calls_from(js_graph, "Circle#area().")


async def test_js_calls_are_resolved_provenance(js_graph: CodeGraph) -> None:
    nodes = (await js_graph.store.graph.query(GraphQuery(kinds=[NodeKind.PACKAGE]))).nodes
    # no external package node — the only import is internal
    assert all(p.provenance.source is Source.RESOLVED for p in nodes)


# --- conformance ------------------------------------------------------------


class TestJavaScriptExtractorConformance(ExtractorConformance):
    @pytest.fixture
    def extractor(self) -> TreeSitterExtractor:
        return TreeSitterExtractor(JAVASCRIPT_PACK, repo="fixture")

    @pytest.fixture
    def sample_file(self) -> SourceFile:
        text = "export class A {\n  m() {\n    return helper();\n  }\n}\n"
        return SourceFile(
            path="a.js",
            text=text,
            language="js",
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
