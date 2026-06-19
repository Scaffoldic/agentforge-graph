"""Spring framework pack (feat-011) — MVC controller routes (Java).

Extracts Spring web endpoints into ``Route`` nodes + ``HANDLED_BY`` edges to the
handler method. A class is a route source only when it is a controller
(``@RestController`` / ``@Controller``, or carries a class-level
``@RequestMapping``) — so a plain Java class never mints routes (ADR-0004). Each
method annotated with ``@GetMapping`` / ``@PostMapping`` / … (or
``@RequestMapping(method=RequestMethod.X)``) becomes a ``Route`` whose path is
the class-level base path joined with the method path, and whose handler is the
``Class#method`` symbol. Intra-file (annotation + method share a file).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from tree_sitter import Language, Parser, Query, QueryCursor
from tree_sitter import Node as TSNode
from tree_sitter_language_pack import get_language

from agentforge_graph.core import (
    Descriptor,
    Edge,
    EdgeKind,
    NodeKind,
    Provenance,
    SourceFile,
    SymbolID,
)
from agentforge_graph.core import Node as GraphNode
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack

_HERE = Path(__file__).parent
# mapping annotation -> HTTP method
_MAPPING = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
}
_CONTROLLER = {"RestController", "Controller"}


@cache
def _language() -> Language:
    return get_language("java")


@cache
def _query_text() -> str:
    return (_HERE / "routes.scm").read_text(encoding="utf-8")


def _text(node: TSNode, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _string(node: TSNode, src: bytes) -> str:
    s = _text(node, src)
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    return s


def _annotations(node: TSNode) -> list[TSNode]:
    """The annotation/marker_annotation nodes on a class or method — directly or
    inside its ``modifiers`` child."""
    out: list[TSNode] = []
    for c in node.named_children:
        if c.type in ("annotation", "marker_annotation"):
            out.append(c)
        elif c.type == "modifiers":
            out.extend(m for m in c.named_children if m.type in ("annotation", "marker_annotation"))
    return out


def _anno_name(anno: TSNode, src: bytes) -> str:
    name = anno.child_by_field_name("name")
    return _text(name, src) if name is not None else ""


def _anno_path(anno: TSNode, src: bytes) -> str:
    """The path string of a mapping annotation: a positional
    ``@GetMapping("/x")`` or a ``value=``/``path=`` element; "" when absent."""
    args = anno.child_by_field_name("arguments")
    if args is None:
        return ""
    for arg in args.named_children:
        if arg.type == "string_literal":
            return _string(arg, src)
        if arg.type == "element_value_pair":
            key = arg.child_by_field_name("key")
            value = arg.child_by_field_name("value")
            if (
                key is not None
                and _text(key, src) in ("value", "path")
                and value is not None
                and value.type == "string_literal"
            ):
                return _string(value, src)
    return ""


def _request_method(anno: TSNode, src: bytes) -> str:
    """The HTTP verb from ``@RequestMapping(method=RequestMethod.X)`` (the tail of
    the field access), or "ALL" when unspecified (Spring matches any method)."""
    args = anno.child_by_field_name("arguments")
    if args is None:
        return "ALL"
    for arg in args.named_children:
        if arg.type != "element_value_pair":
            continue
        key = arg.child_by_field_name("key")
        value = arg.child_by_field_name("value")
        if key is None or _text(key, src) != "method" or value is None:
            continue
        # RequestMethod.PUT -> PUT (the field_access tail)
        if value.type == "field_access":
            field = value.child_by_field_name("field")
            return _text(field, src).upper() if field is not None else "ALL"
        return _text(value, src).rsplit(".", 1)[-1].upper()
    return "ALL"


def _join(base: str, path: str) -> str:
    """Join a class base path with a method path into a single ``/``-separated
    pattern (``/api`` + ``/users`` -> ``/api/users``)."""
    b = base.rstrip("/")
    p = path
    if p and not p.startswith("/"):
        p = "/" + p
    return (b + p) or "/"


class SpringPack(FrameworkPack):
    name = "spring"
    language = "java"
    language_slug = "java"  # SymbolID slug — must match the Java language pack
    version = "1"
    dep_names = ("spring-web", "spring-boot-starter-web", "spring-webmvc")
    import_markers = ("org.springframework.web", "import org.springframework")

    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        src = file.text.encode("utf-8")
        lang = _language()
        root = Parser(lang).parse(src).root_node
        query = Query(lang, _query_text())
        prov = Provenance.parsed(f"pack:{self.name}@{self.version}", commit)
        facts = FrameworkFacts()
        seen: set[str] = set()

        for _pattern, caps in QueryCursor(query).matches(root):
            class_caps = caps.get("decl")
            name_caps = caps.get("class")
            if not (class_caps and name_caps):
                continue
            self._extract_controller(
                class_caps[0], _text(name_caps[0], src), src, repo, file, prov, facts, seen
            )
        return facts

    def _extract_controller(
        self,
        class_node: TSNode,
        class_name: str,
        src: bytes,
        repo: str,
        file: SourceFile,
        prov: Provenance,
        facts: FrameworkFacts,
        seen: set[str],
    ) -> None:
        class_annos = _annotations(class_node)
        names = {_anno_name(a, src) for a in class_annos}
        base_path = ""
        for a in class_annos:
            if _anno_name(a, src) == "RequestMapping":
                base_path = _anno_path(a, src)
        is_controller = bool(names & _CONTROLLER) or "RequestMapping" in names
        if not is_controller:
            return  # not a controller -> not a route source (ADR-0004)

        body = class_node.child_by_field_name("body")
        if body is None:
            return
        for member in body.named_children:
            if member.type != "method_declaration":
                continue
            name_node = member.child_by_field_name("name")
            if name_node is None:
                continue
            for anno in _annotations(member):
                verb_path = self._mapping_for(anno, src)
                if verb_path is None:
                    continue
                method, method_path = verb_path
                self._emit_route(
                    method,
                    _join(base_path, method_path),
                    class_name,
                    _text(name_node, src),
                    member,
                    repo,
                    file,
                    prov,
                    facts,
                    seen,
                )

    def _mapping_for(self, anno: TSNode, src: bytes) -> tuple[str, str] | None:
        """``(http_method, path)`` for a mapping annotation, or None when the
        annotation is not a Spring request mapping."""
        anno_name = _anno_name(anno, src)
        if anno_name in _MAPPING:
            return _MAPPING[anno_name], _anno_path(anno, src)
        if anno_name == "RequestMapping":
            return _request_method(anno, src), _anno_path(anno, src)
        return None

    def _emit_route(
        self,
        method: str,
        path: str,
        class_name: str,
        method_name: str,
        member: TSNode,
        repo: str,
        file: SourceFile,
        prov: Provenance,
        facts: FrameworkFacts,
        seen: set[str],
    ) -> None:
        handler_id = SymbolID.for_symbol(
            self.language_slug,
            repo,
            file.path,
            Descriptor.type(class_name) + Descriptor.method(method_name),
        )
        route_id = SymbolID.for_symbol(
            self.language_slug, repo, file.path, f"route({method} {path})."
        )
        if route_id in seen:
            return
        seen.add(route_id)
        facts.nodes.append(
            GraphNode(
                id=route_id,
                kind=NodeKind.ROUTE,
                name=f"{method} {path}",
                span=(member.start_point[0] + 1, member.end_point[0] + 1),
                attrs={
                    "method": method,
                    "path": path,
                    "framework": self.name,
                    "handler": handler_id,
                },
                provenance=prov,
            )
        )
        facts.edges.append(
            Edge(src=route_id, dst=handler_id, kind=EdgeKind.HANDLED_BY, provenance=prov)
        )


SPRING_PACK = SpringPack()
