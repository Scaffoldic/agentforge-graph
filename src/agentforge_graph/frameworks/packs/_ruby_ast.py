"""Shared tree-sitter helpers for Ruby framework packs (ENH-012).

Framework-agnostic primitives over the Ruby grammar, mirroring the other
``_<lang>_ast`` modules. Used by the Rails pack. Zero ``agentforge`` imports
beyond tree-sitter.
"""

from __future__ import annotations

from functools import cache

from tree_sitter import Language
from tree_sitter import Node as TSNode
from tree_sitter_language_pack import get_language


@cache
def ruby_language() -> Language:
    return get_language("ruby")


def text(node: TSNode, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def ruby_string(node: TSNode, src: bytes) -> str | None:
    """The literal value of a Ruby ``string`` node (quotes stripped), or None for
    a non-literal / interpolated string."""
    if node.type != "string":
        return None
    # interpolation makes a string non-literal -> bail (only string_content kids)
    if any(c.type not in ("string_content",) for c in node.named_children):
        return None
    s = text(node, src)
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    return s


def camelize(name: str) -> str:
    """``users`` -> ``Users``, ``user_profiles`` -> ``UserProfiles`` (Rails
    controller-name convention)."""
    return "".join(p[:1].upper() + p[1:] for p in name.split("_") if p)
