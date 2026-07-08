"""Compiler infrastructure shared by every dialect (feat-015).

A compiler turns a *validated* ``QueryAst`` into a ``CompiledQuery`` — the
backend's native statement plus its bound parameters and the fixed output column
order. Literals are always parameterized (never string-spliced), so there is one
injection-free path on every dialect.

``Compiler`` is a class per dialect (``compile_cypher.py``, ``compile_surreal.py``
in chunk 4), not a function with a ``dialect`` flag — a new dialect is a new
subclass and a new construct is one added emit-arm, never an edit to an existing
branch.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from .ast import QueryAst
from .capability import QuerySettings


@dataclass(frozen=True)
class CompiledQuery:
    """A backend statement + its parameters + the fixed output column order."""

    text: str
    params: dict[str, Any]
    columns: tuple[str, ...]


@dataclass
class ParamAllocator:
    """Allocates ``$p0, $p1, …`` placeholders so literals are never spliced."""

    prefix: str = "p"
    params: dict[str, Any] = field(default_factory=dict)
    _n: int = 0

    def add(self, value: Any) -> str:
        key = f"{self.prefix}{self._n}"
        self._n += 1
        self.params[key] = value
        return key


class Compiler(ABC):
    """AST -> native statement for one backend dialect."""

    dialect: ClassVar[str]

    @abstractmethod
    def compile(self, ast: QueryAst, settings: QuerySettings) -> CompiledQuery:
        """Compile a validated AST, applying the row cap so at most
        ``settings.max_rows`` rows can come back (plus one, to detect
        truncation)."""

    @staticmethod
    def effective_limit(ast: QueryAst, settings: QuerySettings) -> int:
        """The row cap actually applied: the caller's LIMIT clamped to the
        server maximum. The executor fetches this + 1 to detect truncation."""
        if ast.limit is None:
            return settings.max_rows
        return min(ast.limit, settings.max_rows)
