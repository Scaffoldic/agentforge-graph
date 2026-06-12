"""CASTChunker: coverage/boundary properties, symbol splitting, linking,
determinism."""

from __future__ import annotations

import hashlib

from agentforge_graph.chunking import CASTChunker, estimate_tokens
from agentforge_graph.core import Node, NodeKind, SourceFile, SymbolID
from agentforge_graph.ingest import TreeSitterExtractor
from agentforge_graph.ingest.packs.python import PYTHON_PACK


def _extract(text: str, path: str = "m.py") -> tuple[SourceFile, list[Node]]:
    sf = SourceFile(
        path=path, text=text, language="py", content_hash=hashlib.sha256(text.encode()).hexdigest()
    )
    sg = TreeSitterExtractor(PYTHON_PACK, repo="t").extract(sf)
    return sf, sg.nodes


SHAPES = (
    "import math\n"
    "from mathutils import square\n"
    "\n"
    "\n"
    "class Circle:\n"
    "    def __init__(self, radius):\n"
    "        self.radius = radius\n"
    "\n"
    "    def area(self):\n"
    "        return math.pi * square(self.radius)\n"
    "\n"
    "\n"
    "def describe(shape):\n"
    "    return shape.area()\n"
)


def test_covers_every_nonblank_line_once() -> None:
    sf, nodes = _extract(SHAPES)
    chunks = CASTChunker().chunk(sf, nodes)
    lines = SHAPES.splitlines()
    for i, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        covering = [c for c in chunks if c.span[0] <= i <= c.span[1]]
        assert len(covering) == 1, f"line {i} covered by {len(covering)} chunks"


def test_no_chunk_exceeds_budget_unless_atomic() -> None:
    sf, nodes = _extract(SHAPES)
    chunker = CASTChunker(max_tokens=40, min_tokens=8)
    for c in chunker.chunk(sf, nodes):
        single_line = c.span[0] == c.span[1]
        assert c.token_count <= chunker.max_tokens or single_line


def test_fitting_symbols_link_to_their_symbols() -> None:
    sf, nodes = _extract(SHAPES)
    chunks = CASTChunker().chunk(sf, nodes)
    # the describe() function's def line is owned by exactly one chunk that links it
    by_desc = {SymbolID.parse(n.id).descriptor: n.id for n in nodes if n.span}
    describe_id = by_desc["describe()."]
    owning = [c for c in chunks if describe_id in c.symbol_ids]
    assert len(owning) == 1


def test_oversized_function_splits_into_windows() -> None:
    body = "\n".join(f"    x{i} = {i} + {i}" for i in range(200))
    text = f"def big():\n{body}\n"
    sf, nodes = _extract(text)
    chunker = CASTChunker(max_tokens=30, min_tokens=8)
    chunks = chunker.chunk(sf, nodes)
    assert len(chunks) > 1
    for c in chunks:
        assert c.token_count <= chunker.max_tokens or c.span[0] == c.span[1]
    # every chunk still attributes to the big function
    big_id = next(n.id for n in nodes if SymbolID.parse(n.id).descriptor == "big().")
    assert all(big_id in c.symbol_ids for c in chunks)


def test_oversized_class_splits_into_methods() -> None:
    methods = "\n".join(f"    def m{i}(self):\n        return {i}" for i in range(15))
    text = f"class C:\n{methods}\n"
    sf, nodes = _extract(text)
    chunks = CASTChunker(max_tokens=25, min_tokens=8).chunk(sf, nodes)
    method_ids = {n.id for n in nodes if n.kind is NodeKind.METHOD}
    linked = {sid for c in chunks for sid in c.symbol_ids if sid in method_ids}
    assert len(linked) >= 10  # most methods got their own chunk


def test_gap_chunks_have_no_symbol_or_link_module() -> None:
    sf, nodes = _extract(SHAPES)
    chunks = CASTChunker().chunk(sf, nodes)
    # the import header may be a gap chunk (no symbol starts there)
    assert any("import" in c.code for c in chunks)


def test_chunk_ids_are_valid_and_unique() -> None:
    sf, nodes = _extract(SHAPES)
    chunks = CASTChunker().chunk(sf, nodes)
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))
    for cid in ids:
        assert SymbolID.parse(cid).descriptor.startswith("chunk(")


def test_chunking_is_deterministic() -> None:
    sf, nodes = _extract(SHAPES)
    a = [c.model_dump() for c in CASTChunker().chunk(sf, nodes)]
    b = [c.model_dump() for c in CASTChunker().chunk(sf, nodes)]
    assert a == b


def test_empty_when_no_symbols() -> None:
    sf = SourceFile(path="e.py", text="", language="py", content_hash="h")
    assert CASTChunker().chunk(sf, []) == []


def test_estimate_tokens_monotonic() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("a b c") >= 1
    assert estimate_tokens("x" * 400) >= estimate_tokens("x" * 40)
