"""HTTP-client pack (ENH-020 C-full) — outbound cross-service calls (Python).

Captures module-qualified HTTP client calls — ``requests.get("…")``,
``httpx.post("…")`` — as ``ServiceCall`` nodes riding the caller file's
``FileSubgraph`` (the same pass-1 pattern as feat-011 routes). A ``ServiceCall``
records the HTTP ``method`` and the literal ``url``; at federation time these are
matched against ``Route`` nodes in *other* services to draw the cross-service
call graph (C-full pass-2 lives in the federation layer, since member graphs are
separate stores).

Conservative (ADR-0004): only module-qualified calls (``requests``/``httpx`` as a
bare identifier) with a **literal** URL are recorded; a dynamic URL or a
client-instance call is counted as unresolved, never guessed. Zero ``agentforge``
imports (ADR-0001).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from tree_sitter import Parser, Query, QueryCursor

from agentforge_graph.core import Node as GraphNode
from agentforge_graph.core import NodeKind, Provenance, SourceFile, SymbolID
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack
from agentforge_graph.frameworks.packs._python_ast import (
    first_string_in,
    python_language,
    text,
)

_HERE = Path(__file__).parent
_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}
_CLIENT_MODULES = {"requests", "httpx"}


@cache
def _calls_query() -> str:
    return (_HERE / "calls.scm").read_text(encoding="utf-8")


class HttpClientPack(FrameworkPack):
    name = "httpclient"
    language = "python"
    language_slug = "py"
    version = "1"
    dep_names = ("requests", "httpx")
    import_markers = ("import requests", "import httpx", "from requests", "from httpx")

    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        src = file.text.encode("utf-8")
        root = Parser(python_language()).parse(src).root_node
        prov = Provenance.parsed(f"pack:{self.name}@{self.version}", commit)
        facts = FrameworkFacts()
        query = Query(python_language(), _calls_query())
        seen: set[str] = set()
        for _pattern, caps in QueryCursor(query).matches(root):
            obj_caps, method_caps, args_caps = caps.get("obj"), caps.get("method"), caps.get("args")
            if not (obj_caps and method_caps and args_caps):
                continue
            if text(obj_caps[0], src) not in _CLIENT_MODULES:
                continue
            method = text(method_caps[0], src).lower()
            if method not in _HTTP_METHODS:
                continue
            url = first_string_in(args_caps[0], src)
            if url is None:
                facts.unresolved += 1  # dynamic URL — counted, never guessed
                continue
            method_u = method.upper()
            call_node = caps["call"][0]
            line = call_node.start_point[0] + 1
            call_id = SymbolID.for_symbol(
                self.language_slug, repo, file.path, f"servicecall({method_u} {url}@{line})."
            )
            if call_id in seen:
                continue
            seen.add(call_id)
            facts.nodes.append(
                GraphNode(
                    id=call_id,
                    kind=NodeKind.SERVICE_CALL,
                    name=f"{method_u} {url}",
                    span=(line, call_node.end_point[0] + 1),
                    attrs={
                        "method": method_u,
                        "url": url,
                        "path": _url_path(url),
                        "framework": text(obj_caps[0], src),
                    },
                    provenance=prov,
                )
            )
        return facts


def _url_path(url: str) -> str:
    """The path component of a URL for cross-service matching — drops the scheme +
    authority (``http://orders/v1/x`` → ``/v1/x``) and any query/fragment. A bare
    path (``/v1/x``) is returned unchanged."""
    rest = url
    if "://" in rest:
        rest = rest.split("://", 1)[1]
        slash = rest.find("/")
        rest = rest[slash:] if slash != -1 else "/"
    for sep in ("?", "#"):
        if sep in rest:
            rest = rest.split(sep, 1)[0]
    if not rest.startswith("/"):
        rest = "/" + rest
    return rest


HTTPCLIENT_PACK = HttpClientPack()
