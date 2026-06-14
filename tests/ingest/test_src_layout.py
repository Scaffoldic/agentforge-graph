"""BUG-001 regression: in-repo imports resolve under a ``src/`` layout (the
source root is stripped so a file's module key matches how it's imported)."""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.ingest.resolver import _detect_source_roots, _strip_root


def test_detect_and_strip_source_root() -> None:
    paths = [
        "src/mypkg/__init__.py",
        "src/mypkg/util.py",
        "src/mypkg/app.py",
        "pyproject.toml",
    ]
    assert _detect_source_roots(paths) == {"src"}
    assert _strip_root("src/mypkg/util.py", {"src"}) == "mypkg/util.py"
    assert _strip_root("mypkg/util.py", {"src"}) == "mypkg/util.py"  # unaffected


def test_root_layout_has_no_source_root() -> None:
    # a package at the repo root needs no stripping
    assert _detect_source_roots(["mypkg/__init__.py", "mypkg/a.py"]) == set()


async def test_src_layout_imports_and_calls_resolve(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    (repo / "src" / "mypkg").mkdir(parents=True)
    (repo / "src" / "mypkg" / "__init__.py").write_text("")
    (repo / "src" / "mypkg" / "util.py").write_text("def helper(x):\n    return x\n")
    (repo / "src" / "mypkg" / "app.py").write_text(
        "from mypkg.util import helper\n\n\ndef run(v):\n    return helper(v)\n"
    )
    cg = await CodeGraph.index(repo_path=repo)
    try:
        report = cg.stats()
        assert report.resolve.imports_resolved >= 1  # mypkg.app -> mypkg.util (in-repo)
        assert report.resolve.imports_external == 0
        # cross-file CALLS: run -> helper resolved via the now-working import graph
        nodes = (await cg.store.graph.query(GraphQuery(limit=10_000))).nodes
        run_id = next(n.id for n in nodes if SymbolID.parse(n.id).descriptor == "run().")
        callees = {
            SymbolID.parse(n.id).descriptor
            for n in await cg.store.graph.neighbors(run_id, [EdgeKind.CALLS], depth=1)
        }
        assert "helper()." in callees
        # and an IMPORTS edge file->file exists
        imports = [
            e
            for n in nodes
            if n.kind is NodeKind.FILE
            for e in await cg.store.graph.adjacent(n.id, [EdgeKind.IMPORTS], "out")
        ]
        assert imports
    finally:
        await cg.close()


async def test_relative_from_imports_resolve(tmp_path: Path) -> None:
    """BUG-004: `from .util import helper` (relative) binds the name and resolves
    the cross-file CALLS, just like the absolute form — the idiomatic intra-package
    style (validated against pallets/click, where `echo` went 0 -> 18 callers)."""
    repo = tmp_path / "proj"
    (repo / "src" / "mypkg").mkdir(parents=True)
    (repo / "src" / "mypkg" / "__init__.py").write_text("")
    (repo / "src" / "mypkg" / "util.py").write_text("def helper(x):\n    return x\n")
    (repo / "src" / "mypkg" / "app.py").write_text(
        "from .util import helper\n\n\ndef run(v):\n    return helper(v)\n"
    )
    cg = await CodeGraph.index(repo_path=repo)
    try:
        report = cg.stats()
        assert report.resolve.imports_resolved >= 1  # mypkg.app -> mypkg.util (relative)
        assert report.resolve.imports_external == 0  # `.util` is in-repo, not external
        nodes = (await cg.store.graph.query(GraphQuery(limit=10_000))).nodes
        run_id = next(n.id for n in nodes if SymbolID.parse(n.id).descriptor == "run().")
        callees = {
            SymbolID.parse(n.id).descriptor
            for n in await cg.store.graph.neighbors(run_id, [EdgeKind.CALLS], depth=1)
        }
        assert "helper()." in callees  # bare helper() call resolves via the relative import
    finally:
        await cg.close()
