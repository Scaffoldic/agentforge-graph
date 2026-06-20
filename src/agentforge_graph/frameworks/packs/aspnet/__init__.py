"""ASP.NET Core framework pack (ENH-012) — MVC/Web-API controller routes (C#).

Extracts attribute-routed endpoints into ``Route`` nodes + ``HANDLED_BY`` edges
to the handler method. A class is a route source only when it is a controller
(``[ApiController]`` / a class-level ``[Route]``, or a ``Controller`` /
``ControllerBase`` base) — so a plain C# class never mints routes (ADR-0004).
Each method carrying ``[HttpGet("/x")]`` / ``[HttpPost]`` / … becomes a ``Route``
whose path is the class-level ``[Route]`` base joined with the method path
(``[controller]`` expands to the controller name), and whose handler is the
``Class#method`` symbol. Intra-file. Mirrors the Spring pack (attribute ≈
annotation). Minimal-API ``app.MapGet("/x", …)`` is a follow-up.
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
from agentforge_graph.frameworks.packs._csharp_ast import (
    attribute_first_string,
    attribute_name,
    attributes,
    csharp_language,
    text,
)

_HERE = Path(__file__).parent
# [HttpGet]/[HttpPost]/… attribute -> HTTP verb.
_VERB = {
    "HttpGet": "GET",
    "HttpPost": "POST",
    "HttpPut": "PUT",
    "HttpDelete": "DELETE",
    "HttpPatch": "PATCH",
    "HttpHead": "HEAD",
    "HttpOptions": "OPTIONS",
}
_CONTROLLER_BASES = {"Controller", "ControllerBase"}


@cache
def _query_text() -> str:
    return (_HERE / "routes.scm").read_text(encoding="utf-8")


def _join(base: str, path: str) -> str:
    """Join a controller base path with a method path: ``api/users`` + ``{id}``
    -> ``/api/users/{id}``; a method path starting ``/`` or ``~/`` is absolute."""
    if path.startswith(("/", "~/")):
        return "/" + path.lstrip("~/")
    b = "/" + base.strip("/") if base else ""
    p = path.strip("/")
    joined = f"{b}/{p}" if p else b
    return joined or "/"


class AspNetPack(FrameworkPack):
    name = "aspnet"
    language = "csharp"
    language_slug = "cs"  # SymbolID slug — must match the C# language pack
    version = "1"
    dep_names = ()  # C# deps live in .csproj (not scanned); rely on import markers
    import_markers = ("Microsoft.AspNetCore", "Microsoft.AspNet")

    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        src = file.text.encode("utf-8")
        lang = csharp_language()
        root = Parser(lang).parse(src).root_node
        query = Query(lang, _query_text())
        prov = Provenance.parsed(f"pack:{self.name}@{self.version}", commit)
        facts = FrameworkFacts()
        seen: set[str] = set()

        for _pattern, caps in QueryCursor(query).matches(root):
            decl_caps = caps.get("decl")
            name_caps = caps.get("class")
            if not (decl_caps and name_caps):
                continue
            self._extract_controller(
                decl_caps[0], text(name_caps[0], src), src, repo, file, prov, facts, seen
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
        class_attrs = attributes(class_node)
        names = {attribute_name(a, src) for a in class_attrs}
        base_path = ""
        for a in class_attrs:
            if attribute_name(a, src) == "Route":
                base_path = attribute_first_string(a, src) or ""
        is_controller = (
            "ApiController" in names
            or "Route" in names
            or self._has_controller_base(class_node, src)
        )
        if not is_controller:
            return  # not a controller -> not a route source (ADR-0004)
        base_path = self._expand_tokens(base_path, class_name)

        body = class_node.child_by_field_name("body")
        if body is None:
            return
        for member in body.named_children:
            if member.type != "method_declaration":
                continue
            name_node = member.child_by_field_name("name")
            if name_node is None:
                continue
            method_name = text(name_node, src)
            for anno in attributes(member):
                verb = _VERB.get(attribute_name(anno, src))
                if verb is None:
                    continue
                raw = attribute_first_string(anno, src) or ""
                path = _join(base_path, self._expand_tokens(raw, class_name, method_name))
                self._emit_route(
                    verb, path, class_name, method_name, member, repo, file, prov, facts, seen
                )

    def _has_controller_base(self, class_node: TSNode, src: bytes) -> bool:
        base_list = next((c for c in class_node.named_children if c.type == "base_list"), None)
        if base_list is None:
            return False
        return any(
            text(c, src).rsplit(".", 1)[-1] in _CONTROLLER_BASES for c in base_list.named_children
        )

    def _expand_tokens(self, path: str, class_name: str, method_name: str = "") -> str:
        """Expand ASP.NET route tokens: ``[controller]`` -> the controller name
        without its ``Controller`` suffix, ``[action]`` -> the method name."""
        controller = (
            class_name[: -len("Controller")] if class_name.endswith("Controller") else class_name
        )
        out = path.replace("[controller]", controller)
        if method_name:
            out = out.replace("[action]", method_name)
        return out

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
                    "path_pattern": path,
                    "framework": self.name,
                    "handler": handler_id,
                },
                provenance=prov,
            )
        )
        facts.edges.append(
            Edge(src=route_id, dst=handler_id, kind=EdgeKind.HANDLED_BY, provenance=prov)
        )


ASPNET_PACK = AspNetPack()
