"""Gin framework pack (ENH-012) — routes (Go).

Extracts `r.GET("/x", handler)` / `v.POST("/x", mw, handler)` method calls into
``Route`` nodes. The handler is the call's last argument: a **named** function
reference (`ping`) resolves to its symbol → a ``HANDLED_BY`` edge; an
**anonymous** inline handler (`func(c *gin.Context){}`) or a method-value handler
(`h.ping`) still yields the ``Route`` (the API surface) with no edge. A non-route
call (`gin.Default()`, `r.Group(...)`, `r.Use(...)`) or a dynamic (non-literal)
path is skipped/counted, never dropped.

Mirrors the Express pack (method-call routing). Routes carry ``router_var`` (the
``r``/``v`` object) and ``path_pattern`` (== base path) so the generic ENH-011
cross-file stitch composes `r.Group(prefix)` mounts once Gin grows a mount
pass-1. Intra-file at MVP (route call + a named handler in the same file);
cross-file handler imports and group-prefix mounting are follow-ups.
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
from agentforge_graph.frameworks.packs._go_ast import (
    first_arg_string,
    go_language,
    last_named_arg,
    text,
)

_HERE = Path(__file__).parent
# Gin router verbs (uppercase in Go). `Any` registers all methods.
_HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "ANY"}


@cache
def _query_text() -> str:
    return (_HERE / "routes.scm").read_text(encoding="utf-8")


class GinPack(FrameworkPack):
    name = "gin"
    language = "go"
    language_slug = "go"  # SymbolID slug — must match the Go language pack
    version = "1"
    dep_names = ()  # Go deps live in go.mod (not scanned); rely on import markers
    import_markers = ("gin-gonic/gin",)

    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        src = file.text.encode("utf-8")
        lang = go_language()
        root = Parser(lang).parse(src).root_node
        query = Query(lang, _query_text())
        prov = Provenance.parsed(f"pack:{self.name}@{self.version}", commit)
        facts = FrameworkFacts()
        seen: set[str] = set()

        for _pattern, caps in QueryCursor(query).matches(root):
            method_caps = caps.get("method")
            args_caps = caps.get("args")
            call_caps = caps.get("call")
            if not (method_caps and args_caps and call_caps):
                continue
            method = text(method_caps[0], src).upper()
            if method not in _HTTP_METHODS:
                continue  # gin.Default() / r.Group(...) / r.Use(...) — not a route

            path = first_arg_string(args_caps[0], src)
            if path is None:
                facts.unresolved += 1  # dynamic / non-literal path
                continue

            handler_id = self._handler_id(args_caps[0], repo, file, src)
            router_caps = caps.get("router")
            router_var = (
                text(router_caps[0], src)
                if router_caps and router_caps[0].type == "identifier"
                else ""
            )
            route_id = SymbolID.for_symbol(
                self.language_slug, repo, file.path, f"route({method} {path})."
            )
            if route_id in seen:
                continue
            seen.add(route_id)
            route_node = call_caps[0]
            facts.nodes.append(
                GraphNode(
                    id=route_id,
                    kind=NodeKind.ROUTE,
                    name=f"{method} {path}",
                    span=(route_node.start_point[0] + 1, route_node.end_point[0] + 1),
                    attrs={
                        "method": method,
                        "path": path,
                        "path_pattern": path,  # ENH-011: composed by the cross-file pass
                        "router_var": router_var,
                        "framework": self.name,
                        "handler": handler_id or "",
                    },
                    provenance=prov,
                )
            )
            if handler_id is not None:
                facts.edges.append(
                    Edge(src=route_id, dst=handler_id, kind=EdgeKind.HANDLED_BY, provenance=prov)
                )
        return facts

    def _handler_id(self, args: TSNode, repo: str, file: SourceFile, src: bytes) -> str | None:
        """The symbol id of a named handler reference (the last argument), or None
        for an anonymous inline handler / a method value (no local symbol to point
        at — conservative, ADR-0004)."""
        handler = last_named_arg(args)
        if handler is None or handler.type != "identifier":
            return None
        return SymbolID.for_symbol(
            self.language_slug, repo, file.path, Descriptor.method(text(handler, src))
        )


GIN_PACK = GinPack()
