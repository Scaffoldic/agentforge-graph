"""Flask framework pack (feat-011) — routes.

Extracts ``@app.route("/x", methods=[...])`` / blueprint ``@bp.route(...)`` and
the Flask 2.0 shortcuts (``@app.get("/x")`` …) into ``Route`` nodes + ``HANDLED_BY``
edges to the handler ``Function``/method. A ``route`` decorator defaults to
``GET`` and may list several ``methods`` → one ``Route`` per method. Class-based
handlers resolve to their ``Class#method`` symbol; a dynamic (non-literal) path
is counted unresolved, never dropped. Intra-file (decorator and handler share a
file), so it rides the file's ``FileSubgraph`` + feat-004 incrementality.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from tree_sitter import Node as TSNode
from tree_sitter import Parser, Query, QueryCursor

from agentforge_graph.core import (
    Edge,
    EdgeKind,
    NodeKind,
    Provenance,
    SourceFile,
    SymbolID,
)
from agentforge_graph.core import Node as GraphNode
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack
from agentforge_graph.frameworks.packs._python_ast import (
    enclosing_class,
    first_string_in,
    member_descriptor,
    python_language,
    string_list_kwarg,
    text,
)

_HERE = Path(__file__).parent
_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}


@cache
def _query_text() -> str:
    return (_HERE / "routes.scm").read_text(encoding="utf-8")


class FlaskPack(FrameworkPack):
    name = "flask"
    language = "python"
    language_slug = "py"  # SymbolID slug — must match the Python language pack
    version = "1"
    dep_names = ("flask",)
    import_markers = ("import flask", "from flask")

    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        src = file.text.encode("utf-8")
        root = Parser(python_language()).parse(src).root_node
        query = Query(python_language(), _query_text())
        prov = Provenance.parsed(f"pack:{self.name}@{self.version}", commit)
        facts = FrameworkFacts()
        seen: set[str] = set()

        for _pattern, caps in QueryCursor(query).matches(root):
            method_caps = caps.get("method")
            handler_caps = caps.get("handler")
            args_caps = caps.get("args")
            if not (method_caps and handler_caps and args_caps):
                continue
            decorator = text(method_caps[0], src).lower()
            methods = self._methods_for(decorator, args_caps[0], src)
            if methods is None:
                continue  # not a route decorator (e.g. @app.before_request)

            path = first_string_in(args_caps[0], src)
            if path is None:
                facts.unresolved += 1  # dynamic / non-literal path
                continue

            handler = text(handler_caps[0], src)
            handler_id = SymbolID.for_symbol(
                self.language_slug,
                repo,
                file.path,
                member_descriptor(handler, enclosing_class(handler_caps[0], src)),
            )
            route_node = caps["route"][0]
            for method in methods:
                self._emit_route(
                    method, path, handler_id, route_node, repo, file, prov, facts, seen
                )
        return facts

    def _methods_for(self, decorator: str, args: TSNode, src: bytes) -> list[str] | None:
        """The HTTP methods a decorator declares: the ``methods=[...]`` kwarg for
        ``@app.route`` (default ``GET``), the verb itself for ``@app.get`` …, or
        None when the decorator is not a route."""
        if decorator == "route":
            listed = [m.upper() for m in string_list_kwarg(args, "methods", src)]
            return listed or ["GET"]
        if decorator in _HTTP_METHODS:
            return [decorator.upper()]
        return None

    def _emit_route(
        self,
        method: str,
        path: str,
        handler_id: str,
        route_node: TSNode,
        repo: str,
        file: SourceFile,
        prov: Provenance,
        facts: FrameworkFacts,
        seen: set[str],
    ) -> None:
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
                span=(route_node.start_point[0] + 1, route_node.end_point[0] + 1),
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


FLASK_PACK = FlaskPack()
