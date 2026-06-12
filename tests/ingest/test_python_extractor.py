"""TreeSitterExtractor over the Python pack: node/edge shape, descriptors,
method promotion, imports/refs as attrs, determinism, and conformance."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, NodeKind, Source, SourceFile, SymbolID
from agentforge_graph.core.conformance import ExtractorConformance
from agentforge_graph.ingest import TreeSitterExtractor
from agentforge_graph.ingest.packs.python import PYTHON_PACK


def _sourcefile(path: Path, rel: str) -> SourceFile:
    raw = path.read_bytes()
    import hashlib

    return SourceFile(
        path=rel, text=raw.decode(), language="py", content_hash=hashlib.sha256(raw).hexdigest()
    )


@pytest.fixture
def extractor() -> TreeSitterExtractor:
    return TreeSitterExtractor(PYTHON_PACK, repo="fixture", commit="c0")


def test_shapes_nodes_and_descriptors(extractor: TreeSitterExtractor, python_repo: Path) -> None:
    sg = extractor.extract(_sourcefile(python_repo / "shapes.py", "shapes.py"))
    by_desc = {SymbolID.parse(n.id).descriptor: n for n in sg.nodes}
    # file node has empty descriptor
    assert "" in by_desc and by_desc[""].kind is NodeKind.FILE
    # class + nested methods get nested descriptors; method promotion applied
    assert by_desc["Circle#"].kind is NodeKind.CLASS
    assert by_desc["Circle#__init__()."].kind is NodeKind.METHOD
    assert by_desc["Circle#area()."].kind is NodeKind.METHOD
    # a top-level function stays FUNCTION
    assert by_desc["describe()."].kind is NodeKind.FUNCTION
    # spans are 1-based and sensible
    assert by_desc["Circle#"].span is not None and by_desc["Circle#"].span[0] >= 1


def test_contains_edges(extractor: TreeSitterExtractor, python_repo: Path) -> None:
    sg = extractor.extract(_sourcefile(python_repo / "shapes.py", "shapes.py"))
    id_of = {SymbolID.parse(n.id).descriptor: n.id for n in sg.nodes}
    contains = {(e.src, e.dst) for e in sg.edges if e.kind is EdgeKind.CONTAINS}
    # File CONTAINS Circle and describe; Circle CONTAINS its methods
    assert (id_of[""], id_of["Circle#"]) in contains
    assert (id_of[""], id_of["describe()."]) in contains
    assert (id_of["Circle#"], id_of["Circle#area()."]) in contains
    assert (id_of["Circle#"], id_of["Circle#__init__()."]) in contains


def test_imports_recorded_on_file_node(extractor: TreeSitterExtractor, python_repo: Path) -> None:
    sg = extractor.extract(_sourcefile(python_repo / "shapes.py", "shapes.py"))
    file_node = next(n for n in sg.nodes if n.kind is NodeKind.FILE)
    imports = file_node.attrs["imports"]
    modules = {i["module"] for i in imports}
    assert "math" in modules  # external
    assert "mathutils" in modules  # internal
    from_import = next(i for i in imports if i["module"] == "mathutils")
    assert "square" in from_import["names"]


def test_refs_recorded_on_enclosing_def(extractor: TreeSitterExtractor, python_repo: Path) -> None:
    sg = extractor.extract(_sourcefile(python_repo / "shapes.py", "shapes.py"))
    by_desc = {SymbolID.parse(n.id).descriptor: n for n in sg.nodes}
    # area() calls square(...)
    area_refs = {r["name"] for r in by_desc["Circle#area()."].attrs.get("refs", [])}
    assert "square" in area_refs
    # describe() calls shape.area() -> attribute callee "area" recorded (unresolved later)
    describe_refs = {r["name"] for r in by_desc["describe()."].attrs.get("refs", [])}
    assert "area" in describe_refs


def test_intra_file_call_recorded(extractor: TreeSitterExtractor, python_repo: Path) -> None:
    sg = extractor.extract(_sourcefile(python_repo / "mathutils.py", "mathutils.py"))
    by_desc = {SymbolID.parse(n.id).descriptor: n for n in sg.nodes}
    assert {r["name"] for r in by_desc["cube()."].attrs.get("refs", [])} == {"square"}


def test_all_facts_are_parsed_provenance(extractor: TreeSitterExtractor, python_repo: Path) -> None:
    sg = extractor.extract(_sourcefile(python_repo / "shapes.py", "shapes.py"))
    assert all(n.provenance.source is Source.PARSED for n in sg.nodes)
    assert all(e.provenance.source is Source.PARSED for e in sg.edges)
    assert all(n.provenance.commit == "c0" for n in sg.nodes)


def test_extraction_is_deterministic(extractor: TreeSitterExtractor, python_repo: Path) -> None:
    sf = _sourcefile(python_repo / "shapes.py", "shapes.py")
    assert extractor.extract(sf).model_dump() == extractor.extract(sf).model_dump()


def test_overload_disambiguator(python_repo: Path) -> None:
    ex = TreeSitterExtractor(PYTHON_PACK, repo="fixture")
    text = "def f():\n    pass\n\ndef f():\n    pass\n"
    import hashlib

    sf = SourceFile(
        path="o.py",
        text=text,
        language="py",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    descs = {SymbolID.parse(n.id).descriptor for n in ex.extract(sf).nodes}
    assert "f()." in descs
    assert "f(+1)()." in descs


class TestTreeSitterExtractorConformance(ExtractorConformance):
    @pytest.fixture
    def extractor(self) -> TreeSitterExtractor:
        return TreeSitterExtractor(PYTHON_PACK, repo="fixture")

    @pytest.fixture
    def sample_file(self) -> SourceFile:
        import hashlib

        text = "class A:\n    def m(self):\n        return helper()\n"
        return SourceFile(
            path="a.py",
            text=text,
            language="py",
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
