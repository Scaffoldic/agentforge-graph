"""The fixed v1 design-pattern taxonomy (feat-012).

A ``PatternTag`` is a shared taxonomy node (one per pattern name); a ``TAGGED``
edge goes code-symbol → ``PatternTag`` with confidence + rationale in attrs.
The list is locked at v1 (GoF core + architectural roles); extensible by config
later. See spec §4.2.
"""

from __future__ import annotations

from agentforge_graph.core import SymbolID

TAXONOMY_V1: tuple[str, ...] = (
    "Singleton",
    "Factory",
    "Builder",
    "Adapter",
    "Facade",
    "Observer",
    "Strategy",
    "Decorator",
    "Repository",
    "Service",
    "Controller",
    "DTO",
    "ValueObject",
)

_PATTERN_PATH = "<taxonomy>"


def is_pattern(name: str) -> bool:
    return name in TAXONOMY_V1


def pattern_tag_id(repo: str, pattern: str) -> str:
    """Stable id for a taxonomy node — a shared singleton per pattern name."""
    return SymbolID.for_symbol("pattern", repo, _PATTERN_PATH, f"{pattern}.")
