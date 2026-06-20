"""Shared tree-sitter helpers for C# framework packs (ENH-012).

Framework-agnostic primitives over the C# grammar, mirroring ``_js_ast`` /
``_go_ast``. Used by the ASP.NET pack (attribute-driven controllers, like
Spring's annotations). Zero ``agentforge`` imports beyond tree-sitter.
"""

from __future__ import annotations

from functools import cache

from tree_sitter import Language
from tree_sitter import Node as TSNode
from tree_sitter_language_pack import get_language


@cache
def csharp_language() -> Language:
    return get_language("c_sharp")


def text(node: TSNode, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def strip_quotes(s: str) -> str:
    # C# verbatim/interpolated prefixes (@, $) sit outside the quotes.
    body = s
    while body[:1] in ("@", "$"):
        body = body[1:]
    if len(body) >= 2 and body[0] == '"' and body[-1] == '"':
        return body[1:-1]
    return body


def attributes(decl: TSNode) -> list[TSNode]:
    """The ``attribute`` nodes on a class/method declaration — C# groups them in
    ``attribute_list`` children (one or more, each `[A, B]`)."""
    out: list[TSNode] = []
    for c in decl.named_children:
        if c.type == "attribute_list":
            out.extend(a for a in c.named_children if a.type == "attribute")
    return out


def attribute_name(attr: TSNode, src: bytes) -> str:
    """The attribute's name — the tail of a possibly-qualified name
    (``Microsoft.AspNetCore.Mvc.HttpGet`` → ``HttpGet``)."""
    name = attr.child_by_field_name("name")
    if name is None:
        return ""
    return text(name, src).rsplit(".", 1)[-1]


def attribute_first_string(attr: TSNode, src: bytes) -> str | None:
    """The first string-literal argument of an attribute (a route path), or None
    when the attribute has no string argument."""
    for c in attr.named_children:
        if c.type != "attribute_argument_list":
            continue
        node = _first_string(c)
        return strip_quotes(text(node, src)) if node is not None else None
    return None


def _first_string(node: TSNode) -> TSNode | None:
    if node.type in ("string_literal", "verbatim_string_literal", "raw_string_literal"):
        return node
    for c in node.named_children:
        found = _first_string(c)
        if found is not None:
            return found
    return None
