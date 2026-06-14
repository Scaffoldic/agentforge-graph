"""TypeScript pack: extraction, relative-import resolution, end-to-end CALLS —
proof the language harness generalizes beyond Python."""

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
from agentforge_graph.ingest.packs.python import PYTHON_PACK
from agentforge_graph.ingest.packs.typescript import TYPESCRIPT_PACK

FIXTURES = Path(__file__).parent / "fixtures" / "typescript"


def _sf(path: Path, rel: str) -> SourceFile:
    raw = path.read_bytes()
    return SourceFile(
        path=rel, text=raw.decode(), language="ts", content_hash=hashlib.sha256(raw).hexdigest()
    )


def _extractor() -> TreeSitterExtractor:
    return TreeSitterExtractor(TYPESCRIPT_PACK, repo="fixture", commit="c0")


# --- pack module resolution -------------------------------------------------


def test_ts_module_path_is_relative_style() -> None:
    assert TYPESCRIPT_PACK.module_path("mathutils.ts") == "mathutils"
    assert TYPESCRIPT_PACK.module_path("a/b/c.ts") == "a/b/c"  # not dotted


def test_ts_resolve_import() -> None:
    assert TYPESCRIPT_PACK.resolve_import("shapes.ts", "./mathutils") == "mathutils"
    assert TYPESCRIPT_PACK.resolve_import("a/b.ts", "../util/x") == "util/x"
    assert TYPESCRIPT_PACK.resolve_import("a/b.ts", "react") == "react"  # external, unchanged


def test_python_module_resolution_unchanged() -> None:
    assert PYTHON_PACK.module_path("a/b/c.py") == "a.b.c"
    assert PYTHON_PACK.resolve_import("x.py", "os") == "os"


def test_registry_includes_typescript() -> None:
    assert TYPESCRIPT_PACK in BUILTIN_PACKS
    reg = PackRegistry(BUILTIN_PACKS)
    assert reg.for_extension(".ts") is TYPESCRIPT_PACK
    assert reg.for_slug("ts") is TYPESCRIPT_PACK


# --- extraction -------------------------------------------------------------


def test_ts_nodes_descriptors_and_method_promotion() -> None:
    sg = _extractor().extract(_sf(FIXTURES / "shapes.ts", "shapes.ts"))
    by_desc = {SymbolID.parse(n.id).descriptor: n for n in sg.nodes}
    assert by_desc["Circle#"].kind is NodeKind.CLASS
    assert by_desc["Circle#area()."].kind is NodeKind.METHOD  # promoted (nested in class)
    assert by_desc["Circle#constructor()."].kind is NodeKind.METHOD
    assert by_desc["describe()."].kind is NodeKind.FUNCTION  # top-level


def test_ts_abstract_class_extracted() -> None:
    # BUG-005: `abstract class` is a distinct grammar node (abstract_class_declaration);
    # it must extract as a Class with methods promoted, like a concrete class.
    src = (
        "export abstract class ZodType {\n"
        "  parse(x: unknown) {\n"
        "    return x;\n"
        "  }\n"
        "}\n"
        "export class ZodString extends ZodType {\n"
        "  check() {\n"
        "    return true;\n"
        "  }\n"
        "}\n"
    )
    sf = SourceFile(
        path="t.ts",
        text=src,
        language="ts",
        content_hash=hashlib.sha256(src.encode()).hexdigest(),
    )
    by_desc = {SymbolID.parse(n.id).descriptor: n for n in _extractor().extract(sf).nodes}
    assert by_desc["ZodType#"].kind is NodeKind.CLASS  # abstract class now captured
    assert by_desc["ZodType#parse()."].kind is NodeKind.METHOD  # its method promoted + nested
    assert by_desc["ZodString#"].kind is NodeKind.CLASS  # concrete sibling unaffected


def test_ts_imports_and_refs_recorded() -> None:
    sg = _extractor().extract(_sf(FIXTURES / "shapes.ts", "shapes.ts"))
    file_node = next(n for n in sg.nodes if n.kind is NodeKind.FILE)
    imp = file_node.attrs["imports"][0]
    assert imp["module"] == "./mathutils"
    assert "square" in imp["names"]
    by_desc = {SymbolID.parse(n.id).descriptor: n for n in sg.nodes}
    assert "square" in {r["name"] for r in by_desc["Circle#area()."].attrs.get("refs", [])}


def test_ts_signature_captured() -> None:
    sg = _extractor().extract(_sf(FIXTURES / "mathutils.ts", "mathutils.ts"))
    by_desc = {SymbolID.parse(n.id).descriptor: n for n in sg.nodes}
    assert by_desc["square()."].attrs["signature"].startswith("function square")


# --- end-to-end resolution --------------------------------------------------


@pytest.fixture
async def ts_graph(tmp_path: Path) -> AsyncIterator[CodeGraph]:
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


async def test_ts_index_report(ts_graph: CodeGraph) -> None:
    report = ts_graph.stats()
    assert report.files_indexed == 2
    assert report.by_node_kind.get("Class") == 1
    assert report.by_node_kind.get("Method") == 2  # constructor, area
    assert report.resolve.refs_resolved == 2  # cube->square, area->square
    assert report.resolve.imports_resolved == 1  # shapes -> mathutils (relative)


async def test_ts_intra_file_call(ts_graph: CodeGraph) -> None:
    assert "square()." in await _calls_from(ts_graph, "cube().")


async def test_ts_cross_file_call_via_relative_import(ts_graph: CodeGraph) -> None:
    # area() calls square, imported via "./mathutils" -> resolves cross-file
    assert "square()." in await _calls_from(ts_graph, "Circle#area().")


async def test_ts_calls_are_resolved_provenance(ts_graph: CodeGraph) -> None:
    nodes = (await ts_graph.store.graph.query(GraphQuery(kinds=[NodeKind.PACKAGE]))).nodes
    # no external package node — the only import is internal
    assert all(p.provenance.source is Source.RESOLVED for p in nodes)


# --- conformance ------------------------------------------------------------


class TestTypeScriptExtractorConformance(ExtractorConformance):
    @pytest.fixture
    def extractor(self) -> TreeSitterExtractor:
        return TreeSitterExtractor(TYPESCRIPT_PACK, repo="fixture")

    @pytest.fixture
    def sample_file(self) -> SourceFile:
        text = "export class A {\n  m(): number {\n    return helper();\n  }\n}\n"
        return SourceFile(
            path="a.ts",
            text=text,
            language="ts",
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
