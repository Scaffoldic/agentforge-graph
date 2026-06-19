"""Shared tree-sitter helpers for JS/TS framework packs (feat-011).

Framework-agnostic primitives over the JavaScript and TypeScript grammars (which
share the node types these touch). Used by the Express pack and any future JS/TS
pack (NestJS). Zero ``agentforge`` imports beyond tree-sitter.
"""

from __future__ import annotations

from functools import cache

from tree_sitter import Language
from tree_sitter import Node as TSNode
from tree_sitter_language_pack import get_language

# SymbolID slug -> tree-sitter grammar name.
_GRAMMAR = {"js": "javascript", "ts": "typescript"}


@cache
def js_language(slug: str) -> Language:
    """The tree-sitter ``Language`` for a JS/TS SymbolID slug (``js``/``ts``)."""
    return get_language(_GRAMMAR[slug])


def text(node: TSNode, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] in "\"'`" and s[-1] == s[0]:
        return s[1:-1]
    return s


def string_value(node: TSNode, src: bytes) -> str | None:
    """The literal value of a ``string`` node (quotes stripped), or None when the
    node is not a plain string literal."""
    if node.type != "string":
        return None
    return strip_quotes(text(node, src))


def first_arg_string(args: TSNode, src: bytes) -> str | None:
    """The first argument's string-literal value, or None when it is missing or
    non-literal (a computed/templated path)."""
    if not args.named_children:
        return None
    return string_value(args.named_children[0], src)


def last_named_arg(args: TSNode) -> TSNode | None:
    """The last argument node — Express's route handler (a function reference or
    an inline function), after any middleware arguments."""
    kids = args.named_children
    return kids[-1] if kids else None
