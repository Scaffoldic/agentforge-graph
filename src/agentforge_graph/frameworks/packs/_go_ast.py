"""Shared tree-sitter helpers for Go framework packs (ENH-012).

Framework-agnostic primitives over the Go grammar, mirroring ``_js_ast`` /
``_python_ast``. Used by the Gin pack (and any future Go pack — Echo, Fiber, all
of which route via ``r.METHOD(path, handler)`` method calls). Zero ``agentforge``
imports beyond tree-sitter.
"""

from __future__ import annotations

from functools import cache

from tree_sitter import Language
from tree_sitter import Node as TSNode
from tree_sitter_language_pack import get_language


@cache
def go_language() -> Language:
    return get_language("go")


def text(node: TSNode, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def go_string(node: TSNode, src: bytes) -> str | None:
    """The literal value of a Go string node — both ``"/x"``
    (``interpreted_string_literal``) and `` `/x` `` (``raw_string_literal``) —
    with the delimiters stripped; None for a non-literal (a computed path)."""
    if node.type not in ("interpreted_string_literal", "raw_string_literal"):
        return None
    s = text(node, src)
    if len(s) >= 2 and s[0] in '"`' and s[-1] == s[0]:
        return s[1:-1]
    return s


def first_arg_string(args: TSNode, src: bytes) -> str | None:
    """The first argument's string value, or None when missing/non-literal."""
    if not args.named_children:
        return None
    return go_string(args.named_children[0], src)


def last_named_arg(args: TSNode) -> TSNode | None:
    """The last argument node — the route handler, after any middleware."""
    kids = args.named_children
    return kids[-1] if kids else None
