"""``CASTChunker`` — AST-aware chunking via split-then-merge over the symbol
spans feat-002 already extracted (no re-parse). Partitions a file's lines
into contiguous chunks that honour symbol boundaries: a symbol that fits the
budget is never split and never fused with another; oversized symbols recurse
into nested children (a class → per-method chunks) and finally line windows;
small inter-symbol gaps (imports, module code) merge up to the budget.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

from agentforge_graph.core import Node, SourceFile, SymbolID

from .chunk import Chunk
from .tokens import estimate_tokens

_Range = tuple[int, int]


class Chunker(ABC):
    @abstractmethod
    def chunk(self, file: SourceFile, symbols: list[Node]) -> list[Chunk]:
        """Chunks for ``file``, given its symbol nodes (with spans)."""


class CASTChunker(Chunker):
    def __init__(self, max_tokens: int = 512, min_tokens: int = 64) -> None:
        self.max_tokens = max_tokens
        self.min_tokens = min_tokens

    def chunk(self, file: SourceFile, symbols: list[Node]) -> list[Chunk]:
        lines = file.text.splitlines()
        n = len(lines)
        spanned = [s for s in symbols if s.span is not None]
        if not spanned or n == 0:
            return []
        repo = SymbolID.parse(spanned[0].id).repo
        lang = file.language

        toplevel = [s for s in spanned if not any(_contains(o, s) for o in spanned)]
        toplevel.sort(key=lambda s: _span(s)[0])

        ranges: list[_Range] = []
        cursor = 1
        for sym in toplevel:
            start, end = _span(sym)
            if start > cursor:
                self._window(cursor, start - 1, lines, ranges)
            self._emit_symbol(start, end, lines, spanned, ranges)
            cursor = end + 1
        if cursor <= n:
            self._window(cursor, n, lines, ranges)

        ranges = [(a, b) for (a, b) in ranges if self._slice(lines, a, b).strip()]
        ranges = self._merge_gaps(ranges, lines, spanned)

        chunks: list[Chunk] = []
        for seq, (a, b) in enumerate(ranges):
            code = self._slice(lines, a, b)
            sym_ids = [s.id for s in spanned if _overlaps((a, b), _span(s))]
            text = f"{file.path} | {self._qualify(sym_ids)}\n{code}"
            content_hash = hashlib.sha256(
                f"{text}|{self.max_tokens}|{self.min_tokens}".encode()
            ).hexdigest()
            chunks.append(
                Chunk(
                    id=SymbolID.for_symbol(lang, repo, file.path, f"chunk({seq})."),
                    text=text,
                    code=code,
                    token_count=estimate_tokens(code),
                    path=file.path,
                    span=(a, b),
                    content_hash=content_hash,
                    symbol_ids=sym_ids,
                    seq=seq,
                )
            )
        return chunks

    # --- range production -----------------------------------------------

    def _emit_symbol(
        self, start: int, end: int, lines: list[str], symbols: list[Node], out: list[_Range]
    ) -> None:
        if estimate_tokens(self._slice(lines, start, end)) <= self.max_tokens:
            out.append((start, end))
            return
        within = [
            s
            for s in symbols
            if start <= _span(s)[0] and _span(s)[1] <= end and _span(s) != (start, end)
        ]
        direct = [c for c in within if not any(o is not c and _contains(o, c) for o in within)]
        direct.sort(key=lambda s: _span(s)[0])
        if not direct:  # leaf symbol still too big -> line windows (logged by report)
            self._window(start, end, lines, out)
            return
        cursor = start
        for child in direct:
            cs, ce = _span(child)
            if cs > cursor:
                self._window(cursor, cs - 1, lines, out)  # header / gap before child
            self._emit_symbol(cs, ce, lines, symbols, out)
            cursor = ce + 1
        if cursor <= end:
            self._window(cursor, end, lines, out)

    def _window(self, start: int, end: int, lines: list[str], out: list[_Range]) -> None:
        acc = start
        for ln in range(start, end + 1):
            if ln > acc and estimate_tokens(self._slice(lines, acc, ln)) > self.max_tokens:
                out.append((acc, ln - 1))
                acc = ln
        out.append((acc, end))

    def _merge_gaps(
        self, ranges: list[_Range], lines: list[str], symbols: list[Node]
    ) -> list[_Range]:
        def is_gap(r: _Range) -> bool:
            # a gap overlaps no symbol — so function-body windows are NOT gaps
            return not any(_overlaps(r, _span(s)) for s in symbols)

        out: list[_Range] = []
        for r in ranges:
            if out and is_gap(out[-1]) and is_gap(r):
                merged = (out[-1][0], r[1])
                if estimate_tokens(self._slice(lines, *merged)) <= self.max_tokens:
                    out[-1] = merged
                    continue
            out.append(r)
        return out

    # --- helpers --------------------------------------------------------

    @staticmethod
    def _slice(lines: list[str], a: int, b: int) -> str:
        return "\n".join(lines[a - 1 : b])

    @staticmethod
    def _qualify(symbol_ids: list[str]) -> str:
        if not symbol_ids:
            return "module"
        return SymbolID.parse(symbol_ids[0]).descriptor or "module"


def _span(node: Node) -> tuple[int, int]:
    assert node.span is not None
    return node.span


def _contains(outer: Node, inner: Node) -> bool:
    o, i = _span(outer), _span(inner)
    return o[0] <= i[0] and i[1] <= o[1] and o != i


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return not (a[1] < b[0] or b[1] < a[0])
