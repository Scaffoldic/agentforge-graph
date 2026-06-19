"""Express framework pack (feat-011) — routes (JavaScript + TypeScript).

Extracts `app.get('/x', handler)` / `router.post('/x', mw, handler)` calls into
``Route`` nodes. The handler is the call's last argument: a **named** function
reference resolves to its symbol → a ``HANDLED_BY`` edge; an **anonymous** inline
handler (`(req, res) => {}`) still yields the ``Route`` (the API surface) but no
edge (recorded in ``attrs.handler = ""``). A non-route call (`app.use`,
`app.listen`) or a dynamic (non-literal) path is skipped/counted, never dropped.

The pack spans both sibling languages: it extracts over ``.js`` and ``.ts`` and
builds handler symbol ids with the *file's* slug (so a `.ts` handler resolves to
its TS symbol). Intra-file (the route call and a named handler defined in the
same file); cross-file handler imports and `app.use('/p', router)` prefix
mounting are follow-ups.
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
from agentforge_graph.frameworks.packs._js_ast import (
    first_arg_string,
    js_language,
    last_named_arg,
    text,
)

_HERE = Path(__file__).parent
_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "all"}


@cache
def _query_text() -> str:
    return (_HERE / "routes.scm").read_text(encoding="utf-8")


class ExpressPack(FrameworkPack):
    name = "express"
    language = "javascript/typescript"
    language_slug = "js"  # primary; `slugs` spans js+ts and extract uses file.language
    version = "1"
    dep_names = ("express",)
    import_markers = (
        "require('express')",
        'require("express")',
        "from 'express'",
        'from "express"',
    )

    @property
    def slugs(self) -> tuple[str, ...]:
        return ("js", "ts")

    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        slug = file.language  # "js" or "ts" — the file's own slug
        src = file.text.encode("utf-8")
        lang = js_language(slug)
        root = Parser(lang).parse(src).root_node
        query = Query(lang, _query_text())
        prov = Provenance.parsed(f"pack:{self.name}@{self.version}", commit)
        facts = FrameworkFacts()
        seen: set[str] = set()

        for _pattern, caps in QueryCursor(query).matches(root):
            method_caps = caps.get("method")
            args_caps = caps.get("args")
            route_caps = caps.get("call")
            if not (method_caps and args_caps and route_caps):
                continue
            method = text(method_caps[0], src).lower()
            if method not in _HTTP_METHODS:
                continue  # app.use / app.listen / a non-router method call

            path = first_arg_string(args_caps[0], src)
            if path is None:
                facts.unresolved += 1  # dynamic / non-literal path
                continue

            handler_id = self._handler_id(args_caps[0], slug, repo, file, src)
            method_u = "ALL" if method == "all" else method.upper()
            route_id = SymbolID.for_symbol(slug, repo, file.path, f"route({method_u} {path}).")
            if route_id in seen:
                continue
            seen.add(route_id)
            route_node = route_caps[0]
            facts.nodes.append(
                GraphNode(
                    id=route_id,
                    kind=NodeKind.ROUTE,
                    name=f"{method_u} {path}",
                    span=(route_node.start_point[0] + 1, route_node.end_point[0] + 1),
                    attrs={
                        "method": method_u,
                        "path": path,
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

    def _handler_id(
        self, args: TSNode, slug: str, repo: str, file: SourceFile, src: bytes
    ) -> str | None:
        """The symbol id of a named handler reference (the last argument), or None
        for an anonymous inline handler (no symbol to point at)."""
        handler = last_named_arg(args)
        if handler is None or handler.type != "identifier":
            return None
        return SymbolID.for_symbol(slug, repo, file.path, Descriptor.method(text(handler, src)))


EXPRESS_PACK = ExpressPack()
