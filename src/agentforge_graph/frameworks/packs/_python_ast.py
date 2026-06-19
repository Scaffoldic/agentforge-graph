"""Shared tree-sitter helpers for Python framework packs (feat-011).

Framework-agnostic primitives over the Python grammar — used by the SQLAlchemy
and Django ORM packs (and any future Python pack: Flask, FastAPI class views).
Zero ``agentforge`` imports beyond tree-sitter; no framework semantics here.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import cache

from tree_sitter import Language
from tree_sitter import Node as TSNode
from tree_sitter_language_pack import get_language

from agentforge_graph.core import Descriptor


@cache
def python_language() -> Language:
    return get_language("python")


def text(node: TSNode, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    return s


def callee_name(call: TSNode, src: bytes) -> str:
    """Last segment of a call's function name: ``Column`` for both ``Column(...)``
    and ``sa.Column(...)`` / ``models.ForeignKey(...)``."""
    fn = call.child_by_field_name("function")
    if fn is None:
        return ""
    if fn.type == "attribute":
        attr = fn.child_by_field_name("attribute")
        return text(attr, src) if attr is not None else ""
    return text(fn, src)


def class_body(class_node: TSNode) -> TSNode | None:
    return class_node.child_by_field_name("body")


def dotted_tail(node: TSNode, src: bytes) -> str:
    """Last segment of an identifier or attribute node — ``Model`` for both
    ``Model`` and ``models.Model`` / ``db.models.Model``; ``User`` for
    ``myapp.User``. "" for anything else."""
    if node.type == "attribute":
        attr = node.child_by_field_name("attribute")
        return text(attr, src) if attr is not None else ""
    if node.type == "identifier":
        return text(node, src)
    return ""


def base_classes(class_node: TSNode, src: bytes) -> list[str]:
    """The dotted-tail names of a class's base classes: ``["Model"]`` for
    ``class User(models.Model)``, ``["TimestampedModel"]`` for a subclass."""
    supers = class_node.child_by_field_name("superclasses")
    if supers is None:
        return []
    return [t for c in supers.named_children if (t := dotted_tail(c, src))]


def iter_class_assignments(body: TSNode, src: bytes) -> Iterator[tuple[str, TSNode, TSNode]]:
    """Yield ``(lhs_name, assignment_node, rhs_node)`` for each class-level
    ``name = <expr>``. The block may hold the assignment directly or wrapped in
    an ``expression_statement``; non-identifier LHS is skipped."""
    for stmt in body.named_children:
        if stmt.type == "assignment":
            assign = stmt
        elif stmt.type == "expression_statement" and stmt.named_children:
            assign = stmt.named_children[0]
            if assign.type != "assignment":
                continue
        else:
            continue
        left = assign.child_by_field_name("left")
        right = assign.child_by_field_name("right")
        if left is None or left.type != "identifier" or right is None:
            continue
        yield text(left, src), assign, right


def first_string_arg(call: TSNode, src: bytes) -> str:
    """The first string-literal positional arg, stripped (``"Post"`` in
    ``relationship("Post")``); "" when there is no string positional."""
    args = call.child_by_field_name("arguments")
    if args is None:
        return ""
    for arg in args.named_children:
        if arg.type == "string":
            return strip_quotes(text(arg, src))
    return ""


def enclosing_class(node: TSNode, src: bytes) -> str | None:
    """The name of the nearest enclosing ``class_definition``, or None for a
    module-level definition — lets a class-based handler/consumer resolve to its
    ``Class#method`` symbol."""
    anc = node.parent
    while anc is not None:
        if anc.type == "class_definition":
            name = anc.child_by_field_name("name")
            return text(name, src) if name is not None else None
        anc = anc.parent
    return None


def member_descriptor(name: str, enclosing: str | None) -> str:
    """``Class#method().`` for a method, ``method().`` for a free function."""
    if enclosing is not None:
        return Descriptor.type(enclosing) + Descriptor.method(name)
    return Descriptor.method(name)


def first_string_in(args: TSNode, src: bytes) -> str | None:
    """The first string-literal positional arg (a route path), or None when the
    arg is dynamic/non-literal."""
    for child in args.named_children:
        if child.type == "string":
            return strip_quotes(text(child, src))
    return None


def string_list_kwarg(args: TSNode, name: str, src: bytes) -> list[str]:
    """The string elements of a ``name=[...]`` keyword argument (e.g. Flask's
    ``methods=["GET", "POST"]``), in order; [] when absent or non-literal."""
    for arg in args.named_children:
        if arg.type != "keyword_argument":
            continue
        key = arg.child_by_field_name("name")
        value = arg.child_by_field_name("value")
        if key is None or text(key, src) != name or value is None or value.type != "list":
            continue
        return [strip_quotes(text(e, src)) for e in value.named_children if e.type == "string"]
    return []


def first_positional_arg(call: TSNode, src: bytes) -> TSNode | None:
    """The first non-keyword argument node, or None — the target in
    ``ForeignKey(User)`` / ``ForeignKey("app.User")`` / ``CharField(...)``."""
    args = call.child_by_field_name("arguments")
    if args is None:
        return None
    for arg in args.named_children:
        if arg.type == "keyword_argument":
            continue
        return arg
    return None
