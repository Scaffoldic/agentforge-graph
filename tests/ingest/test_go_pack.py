"""Go pack: extraction + directory-package import resolution.

Go is the first directory-level pack (a package is a dir; same-package files
reference each other with no import; import paths are full module paths the
resolver suffix-matches to a repo dir). These tests prove the harness
generalizes to that model.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SourceFile, SymbolID
from agentforge_graph.core.conformance import ExtractorConformance
from agentforge_graph.ingest import CodeGraph, PackRegistry, TreeSitterExtractor
from agentforge_graph.ingest.packs import BUILTIN_PACKS
from agentforge_graph.ingest.packs.go import GO_PACK
from agentforge_graph.ingest.source import read_go_module


def _extractor() -> TreeSitterExtractor:
    return TreeSitterExtractor(GO_PACK, repo="fixture", commit="c0")


def _sf(text: str, path: str) -> SourceFile:
    return SourceFile(
        path=path, text=text, language="go", content_hash=hashlib.sha256(text.encode()).hexdigest()
    )


# --- pack module resolution -------------------------------------------------


def test_go_module_path_is_directory_level() -> None:
    # a package key is the file's *directory* (every .go file in a dir is one pkg)
    assert GO_PACK.module_path("internal/bar/bar.go") == "internal/bar"
    assert GO_PACK.module_path("geo/circle.go") == "geo"
    assert GO_PACK.module_path("main.go") == ""  # repo-root package


def test_go_resolve_import_is_identity() -> None:
    # the full import path is returned as-is; the resolver suffix-matches it
    assert GO_PACK.resolve_import("main.go", "example.com/m/internal/bar") == (
        "example.com/m/internal/bar"
    )
    assert GO_PACK.resolve_import("a/b.go", "fmt") == "fmt"


def test_registry_includes_go() -> None:
    assert GO_PACK in BUILTIN_PACKS
    reg = PackRegistry(BUILTIN_PACKS)
    assert reg.for_extension(".go") is GO_PACK
    assert reg.for_slug("go") is GO_PACK


# --- extraction -------------------------------------------------------------


def test_go_symbol_surface() -> None:
    src = (
        "package geo\n\n"
        "type Shape interface { Area() float64 }\n"
        "type Circle struct { R float64 }\n"
        "type Celsius float64\n"
        "type Handler func(int) int\n\n"
        "func (c Circle) Area() float64 { return c.R }\n"
        "func New(r float64) Circle { return Circle{R: r} }\n\n"
        "const Pi = 3.14\n"
        "var Default = Circle{R: 1}\n\n"
        "func use() { _ = New(2) }\n"
    )
    by_desc = {
        SymbolID.parse(n.id).descriptor: n for n in _extractor().extract(_sf(src, "geo/c.go")).nodes
    }
    assert by_desc["Shape#"].kind is NodeKind.INTERFACE
    assert by_desc["Circle#"].kind is NodeKind.CLASS  # struct -> Class
    assert by_desc["Celsius."].kind is NodeKind.TYPE_ALIAS  # defined type
    assert by_desc["Handler."].kind is NodeKind.TYPE_ALIAS  # func type
    assert by_desc["Area()."].kind is NodeKind.METHOD  # receiver method
    assert by_desc["New()."].kind is NodeKind.FUNCTION
    assert by_desc["Pi."].kind is NodeKind.VARIABLE  # package const
    assert by_desc["Default."].kind is NodeKind.VARIABLE  # package var


def test_go_imports_recorded() -> None:
    src = 'package m\n\nimport (\n\t"fmt"\n\t"example.com/m/bar"\n)\n'
    sg = _extractor().extract(_sf(src, "m/m.go"))
    file_node = next(n for n in sg.nodes if n.kind is NodeKind.FILE)
    mods = {imp["module"] for imp in file_node.attrs["imports"]}
    assert mods == {"fmt", "example.com/m/bar"}


def test_go_local_const_not_captured() -> None:
    # const/var inside a function body are locals, not package symbols
    src = "package m\nfunc f() {\n\tconst local = 1\n\treturn\n}\n"
    by_desc = {
        SymbolID.parse(n.id).descriptor: n for n in _extractor().extract(_sf(src, "m/m.go")).nodes
    }
    assert "local." not in by_desc
    assert "f()." in by_desc


# --- end-to-end resolution --------------------------------------------------


@pytest.fixture
async def go_repo(tmp_path: Path) -> AsyncIterator[CodeGraph]:
    repo = tmp_path / "proj"
    (repo / "geo").mkdir(parents=True)
    (repo / "internal" / "bar").mkdir(parents=True)
    # same package `geo`, two files: helpers.go calls New() defined in circle.go
    (repo / "geo" / "circle.go").write_text(
        "package geo\nfunc New(r float64) float64 { return r }\n"
    )
    (repo / "geo" / "helpers.go").write_text(
        "package geo\nfunc Helper() float64 { return New(2) }\n"
    )
    (repo / "internal" / "bar" / "bar.go").write_text("package bar\nfunc Do() int { return 1 }\n")
    (repo / "main.go").write_text(
        'package main\n\nimport (\n\t"fmt"\n\t"example.com/m/geo"\n)\n\n'
        "func main() {\n\tfmt.Println(geo.New(1))\n}\n"
    )
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield cg
    finally:
        await cg.close()


async def _calls_from(cg: CodeGraph, name: str) -> set[str]:
    nodes = (await cg.store.graph.query(GraphQuery(limit=10000))).nodes
    sid = next(n.id for n in nodes if n.name == name)
    nbrs = await cg.store.graph.neighbors(sid, [EdgeKind.CALLS], depth=1)
    return {n.name for n in nbrs}


async def test_go_same_package_cross_file_call(go_repo: CodeGraph) -> None:
    # Helper (geo/helpers.go) calls New (geo/circle.go) — same package, no import.
    # The dir-level export merge makes the sibling visible.
    assert "New" in await _calls_from(go_repo, "Helper")


async def test_go_cross_package_import_suffix_match(go_repo: CodeGraph) -> None:
    report = go_repo.stats()
    # `import "example.com/m/geo"` resolves to the in-repo `geo` dir (prefix
    # stripped by suffix-match); `fmt` stays external.
    assert report.resolve.imports_resolved >= 1
    assert report.resolve.imports_external >= 1  # fmt
    nodes = (await go_repo.store.graph.query(GraphQuery(limit=10000))).nodes
    main_file = next(
        n.id for n in nodes if SymbolID.parse(n.id).path == "main.go" and n.kind is NodeKind.FILE
    )
    imps = await go_repo.store.graph.neighbors(main_file, [EdgeKind.IMPORTS], depth=1)
    in_repo = {SymbolID.parse(n.id).path for n in imps if n.kind is NodeKind.FILE}
    assert any(p.startswith("geo/") for p in in_repo)


async def test_go_index_report(go_repo: CodeGraph) -> None:
    report = go_repo.stats()
    assert report.files_indexed == 4
    assert report.by_node_kind.get("Function", 0) >= 3  # New, Helper, Do, main


def test_read_go_module(tmp_path: Path) -> None:
    assert read_go_module(tmp_path) == ""  # no go.mod
    (tmp_path / "go.mod").write_text("module github.com/spf13/cobra\n\ngo 1.21\n")
    assert read_go_module(tmp_path) == "github.com/spf13/cobra"


async def test_go_root_package_import_resolves_via_gomod(tmp_path: Path) -> None:
    # With go.mod present, an import of the *root* module package (dir key "")
    # resolves — the suffix-match alone can't produce "" for the root package.
    repo = tmp_path / "proj"
    (repo / "sub").mkdir(parents=True)
    (repo / "go.mod").write_text("module example.com/m\n\ngo 1.21\n")
    (repo / "api.go").write_text("package m\n\nfunc Root() int { return 1 }\n")
    (repo / "sub" / "s.go").write_text(
        'package sub\n\nimport "example.com/m"\n\nfunc use() int { return m.Root() }\n'
    )
    cg = await CodeGraph.index(repo_path=repo)
    try:
        report = cg.stats()
        assert report.resolve.imports_resolved >= 1  # sub -> root package
        nodes = (await cg.store.graph.query(GraphQuery(limit=10000))).nodes
        sub_file = next(
            n.id
            for n in nodes
            if SymbolID.parse(n.id).path == "sub/s.go" and n.kind is NodeKind.FILE
        )
        imps = await cg.store.graph.neighbors(sub_file, [EdgeKind.IMPORTS], depth=1)
        # the IMPORTS target is a root-package file (api.go, dir key "")
        assert any(SymbolID.parse(n.id).path == "api.go" for n in imps if n.kind is NodeKind.FILE)
    finally:
        await cg.close()


# --- conformance ------------------------------------------------------------


class TestGoExtractorConformance(ExtractorConformance):
    @pytest.fixture
    def extractor(self) -> TreeSitterExtractor:
        return TreeSitterExtractor(GO_PACK, repo="fixture")

    @pytest.fixture
    def sample_file(self) -> SourceFile:
        text = "package a\n\nfunc helper() int { return 1 }\n\nfunc f() int { return helper() }\n"
        return _sf(text, "a/a.go")
