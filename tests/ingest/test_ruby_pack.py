"""Ruby pack: extraction + require_relative (wildcard) resolution."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SourceFile, SymbolID
from agentforge_graph.core.conformance import ExtractorConformance
from agentforge_graph.ingest import CodeGraph, PackRegistry, TreeSitterExtractor
from agentforge_graph.ingest.packs import BUILTIN_PACKS
from agentforge_graph.ingest.packs.ruby import RUBY_PACK


def _extractor() -> TreeSitterExtractor:
    return TreeSitterExtractor(RUBY_PACK, repo="fixture", commit="c0")


def _sf(text: str, path: str) -> SourceFile:
    return SourceFile(
        path=path, text=text, language="rb", content_hash=hashlib.sha256(text.encode()).hexdigest()
    )


def test_registry_includes_ruby() -> None:
    assert RUBY_PACK in BUILTIN_PACKS
    reg = PackRegistry(BUILTIN_PACKS)
    assert reg.for_extension(".rb") is RUBY_PACK
    assert reg.for_slug("rb") is RUBY_PACK


def test_ruby_symbol_surface() -> None:
    src = (
        'require "set"\n'
        'require_relative "./util"\n\n'
        "module Geo\n"
        "  class Circle < Shape\n"
        "    def initialize(r)\n      @r = r\n    end\n"
        "    def area\n      compute(@r)\n    end\n"
        "    def self.build(r)\n      new(r)\n    end\n"
        "  end\n"
        "  PI = 3.14\n"
        "end\n"
    )
    by_desc = {
        SymbolID.parse(n.id).descriptor: n for n in _extractor().extract(_sf(src, "g.rb")).nodes
    }
    assert by_desc["Geo#"].kind is NodeKind.CLASS  # module -> Class
    assert by_desc["Geo#Circle#"].kind is NodeKind.CLASS
    assert by_desc["Geo#Circle#area()."].kind is NodeKind.METHOD  # def nested in class
    assert by_desc["Geo#Circle#build()."].kind is NodeKind.METHOD  # def self.x
    assert by_desc["Geo#PI."].kind is NodeKind.VARIABLE  # constant


def test_ruby_imports_recorded() -> None:
    # only require_relative is captured (it's file-relative + resolvable); plain
    # `require "set"` is load-path based and left to a follow-up.
    src = 'require "set"\nrequire_relative "./helpers/util"\nrequire_relative "thor/command"\n'
    sg = _extractor().extract(_sf(src, "m.rb"))
    file_node = next(n for n in sg.nodes if n.kind is NodeKind.FILE)
    mods = {imp["module"] for imp in file_node.attrs["imports"]}
    assert mods == {"./helpers/util", "thor/command"}  # `set` (plain require) excluded


def test_ruby_bare_require_relative_is_file_relative() -> None:
    # `require_relative "thor/command"` (no `./`) still resolves against the dir
    assert RUBY_PACK.resolve_import("lib/thor.rb", "thor/command") == "lib/thor/command"
    assert RUBY_PACK.resolve_import("lib/thor/x.rb", "../util") == "lib/util"


# --- end-to-end resolution --------------------------------------------------


@pytest.fixture
async def ruby_repo(tmp_path: Path) -> AsyncIterator[CodeGraph]:
    repo = tmp_path / "proj"
    (repo / "lib").mkdir(parents=True)
    (repo / "lib" / "util.rb").write_text("def compute(x)\n  x * 2\nend\n")
    (repo / "lib" / "main.rb").write_text(
        'require "set"\nrequire_relative "util"\n\ndef run\n  compute(3)\nend\n'
    )
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield cg
    finally:
        await cg.close()


async def test_ruby_require_relative_resolves_and_wildcard_binds(ruby_repo: CodeGraph) -> None:
    report = ruby_repo.stats()
    assert report.resolve.imports_resolved >= 1  # main -> util (bare require_relative)
    # the wildcard import makes util's top-level `compute` callable from main
    nodes = (await ruby_repo.store.graph.query(GraphQuery(limit=10000))).nodes
    run = next(n.id for n in nodes if n.name == "run")
    nbrs = await ruby_repo.store.graph.neighbors(run, [EdgeKind.CALLS], depth=1)
    assert "compute" in {n.name for n in nbrs}


# --- conformance ------------------------------------------------------------


class TestRubyExtractorConformance(ExtractorConformance):
    @pytest.fixture
    def extractor(self) -> TreeSitterExtractor:
        return TreeSitterExtractor(RUBY_PACK, repo="fixture")

    @pytest.fixture
    def sample_file(self) -> SourceFile:
        return _sf("def helper\n  1\nend\n\ndef f\n  helper\nend\n", "a.rb")
