"""NestJS framework pack (feat-011) — controller routes (TypeScript).

Extracts NestJS endpoints into ``Route`` nodes + ``HANDLED_BY`` edges. A class is
a route source only when it carries an ``@Controller`` decorator (ADR-0004); its
optional ``@Controller('base')`` argument is the base path. Each method decorated
with ``@Get`` / ``@Post`` / ``@Put`` / ``@Delete`` / ``@Patch`` / ``@All``
becomes a ``Route`` whose path is the base joined with the decorator's path
argument, handled by the ``Class#method`` symbol. TypeScript decorators are
preceding siblings of the node they annotate, so the pack reads the class's
preceding decorators and walks the class body in order.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from tree_sitter import Node as TSNode
from tree_sitter import Parser, Query, QueryCursor

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
from agentforge_graph.frameworks.packs._js_ast import js_language, string_value, text

_HERE = Path(__file__).parent
_SLUG = "ts"
_MAPPING = {
    "Get": "GET",
    "Post": "POST",
    "Put": "PUT",
    "Delete": "DELETE",
    "Patch": "PATCH",
    "All": "ALL",
}


@cache
def _query_text() -> str:
    return (_HERE / "routes.scm").read_text(encoding="utf-8")


def _decorator_name_and_path(dec: TSNode, src: bytes) -> tuple[str, str]:
    """``(name, path)`` for a decorator: ``@Get(':id')`` -> ``("Get", ":id")``,
    ``@Get()`` / ``@Get`` -> ``("Get", "")``."""
    child = dec.named_children[0] if dec.named_children else None
    if child is None:
        return "", ""
    if child.type == "call_expression":
        fn = child.child_by_field_name("function")
        name = text(fn, src) if fn is not None else ""
        args = child.child_by_field_name("arguments")
        path = ""
        if args is not None and args.named_children:
            path = string_value(args.named_children[0], src) or ""
        return name, path
    if child.type == "identifier":
        return text(child, src), ""
    return "", ""


def _preceding_decorators(node: TSNode, src: bytes) -> list[tuple[str, str]]:
    """The ``(name, path)`` of each decorator immediately preceding ``node``
    (TS attaches decorators as previous siblings; an ``export`` keyword may sit
    between)."""
    out: list[tuple[str, str]] = []
    sib = node.prev_sibling
    while sib is not None:
        if sib.type == "decorator":
            out.append(_decorator_name_and_path(sib, src))
        elif sib.is_named:
            break  # a real preceding statement ends the decorator run
        sib = sib.prev_sibling
    return out


def _join(base: str, path: str) -> str:
    """Join NestJS path segments (which omit leading slashes) into one absolute
    pattern: ``users`` + ``:id`` -> ``/users/:id``."""
    segments = [s.strip("/") for s in (base, path) if s.strip("/")]
    return "/" + "/".join(segments) if segments else "/"


class NestJSPack(FrameworkPack):
    name = "nestjs"
    language = "typescript"
    language_slug = _SLUG  # SymbolID slug — must match the TypeScript language pack
    version = "1"
    dep_names = ("@nestjs/common", "@nestjs/core")
    import_markers = ("@nestjs/common", "from '@nestjs", 'from "@nestjs')

    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        src = file.text.encode("utf-8")
        lang = js_language(_SLUG)
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
                class_caps[0], text(name_caps[0], src), src, repo, file, prov, facts, seen
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
        class_decos = _preceding_decorators(class_node, src)
        controller = next((d for d in class_decos if d[0] == "Controller"), None)
        if controller is None:
            return  # not a controller -> not a route source (ADR-0004)
        base_path = controller[1]

        body = class_node.child_by_field_name("body")
        if body is None:
            return
        pending: list[tuple[str, str]] = []
        for member in body.named_children:
            if member.type == "decorator":
                pending.append(_decorator_name_and_path(member, src))
                continue
            if member.type == "method_definition":
                name_node = member.child_by_field_name("name")
                if name_node is not None:
                    for deco_name, deco_path in pending:
                        verb = _MAPPING.get(deco_name)
                        if verb is None:
                            continue
                        self._emit_route(
                            verb,
                            _join(base_path, deco_path),
                            class_name,
                            text(name_node, src),
                            member,
                            repo,
                            file,
                            prov,
                            facts,
                            seen,
                        )
            pending = []

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
            _SLUG, repo, file.path, Descriptor.type(class_name) + Descriptor.method(method_name)
        )
        route_id = SymbolID.for_symbol(_SLUG, repo, file.path, f"route({method} {path}).")
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


NESTJS_PACK = NestJSPack()
