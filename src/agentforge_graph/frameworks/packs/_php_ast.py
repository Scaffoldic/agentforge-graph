"""Shared tree-sitter helpers for PHP framework packs (ENH-012).

Framework-agnostic primitives over the PHP grammar, mirroring the other
``_<lang>_ast`` modules. Used by the Laravel pack. Zero ``agentforge`` imports
beyond tree-sitter.
"""

from __future__ import annotations

from functools import cache

from tree_sitter import Language
from tree_sitter import Node as TSNode
from tree_sitter_language_pack import get_language


@cache
def php_language() -> Language:
    return get_language("php")


def text(node: TSNode, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    return s


def string_value(node: TSNode, src: bytes) -> str | None:
    """The literal value of a PHP string node (``string``/``encapsed_string``),
    quotes stripped; None for a non-literal."""
    if node.type not in ("string", "encapsed_string"):
        return None
    return strip_quotes(text(node, src))


def arg_value(argument: TSNode) -> TSNode:
    """The value node inside a PHP wrapper — a call ``argument`` or an
    ``array_element_initializer``; the node itself when it is not a wrapper."""
    if argument.type in ("argument", "array_element_initializer") and argument.named_children:
        return argument.named_children[0]
    return argument
