"""FastAPI framework pack (feat-011 MVP) — routes only.

Extracts ``@app.get("/x")`` / ``@router.post(...)`` decorators into ``Route``
nodes + ``HANDLED_BY`` edges to the handler ``Function``. Intra-file: the
decorator and handler live in the same file, so the edge endpoints are both in
the file's ``FileSubgraph``. Cross-file ``include_router`` prefix composition
and class-based handlers are follow-ups (counted as unresolved here).
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
_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}


@cache
def _language() -> Language:
    return get_language("python")


@cache
def _query_text() -> str:
    return (_HERE / "routes.scm").read_text(encoding="utf-8")


def _text(node: TSNode, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    return s


def _first_string(args: TSNode, src: bytes) -> str | None:
    """The first string-literal positional arg (the path), or None if the path
    is dynamic/non-literal."""
    for child in args.named_children:
        if child.type == "string":
            return _strip_quotes(_text(child, src))
    return None


def _inside_class(node: TSNode) -> bool:
    anc = node.parent
    while anc is not None:
        if anc.type == "class_definition":
            return True
        anc = anc.parent
    return False


class FastAPIPack(FrameworkPack):
    name = "fastapi"
    language = "python"
    language_slug = "py"  # SymbolID slug — must match the Python language pack
    version = "1"
    dep_names = ("fastapi",)
    import_markers = ("import fastapi", "from fastapi")

    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        src = file.text.encode("utf-8")
        root = Parser(_language()).parse(src).root_node
        query = Query(_language(), _query_text())
        prov = Provenance.parsed(f"pack:{self.name}@{self.version}", commit)
        facts = FrameworkFacts()
        seen: set[str] = set()

        for _pattern, caps in QueryCursor(query).matches(root):
            method_caps = caps.get("method")
            handler_caps = caps.get("handler")
            args_caps = caps.get("args")
            if not (method_caps and handler_caps and args_caps):
                continue
            method = _text(method_caps[0], src).lower()
            if method not in _HTTP_METHODS:
                continue  # @app.middleware / @app.on_event / etc. — not a route

            # A route we recognise but can't pin down statically is counted,
            # not dropped: dynamic path, or a class-based handler (MVP).
            path = _first_string(args_caps[0], src)
            if path is None or _inside_class(handler_caps[0]):
                facts.unresolved += 1
                continue

            handler = _text(handler_caps[0], src)
            handler_id = SymbolID.for_symbol(
                self.language_slug, repo, file.path, Descriptor.method(handler)
            )
            method_u = method.upper()
            route_id = SymbolID.for_symbol(
                self.language_slug, repo, file.path, f"route({method_u} {path})."
            )
            if route_id in seen:
                continue
            seen.add(route_id)
            route_node = caps["route"][0]
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
                        "handler": handler_id,
                    },
                    provenance=prov,
                )
            )
            facts.edges.append(
                Edge(src=route_id, dst=handler_id, kind=EdgeKind.HANDLED_BY, provenance=prov)
            )
        return facts


FASTAPI_PACK = FastAPIPack()
