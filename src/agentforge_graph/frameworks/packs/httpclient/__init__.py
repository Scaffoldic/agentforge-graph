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
    string_kwarg,
    text,
)

_HERE = Path(__file__).parent
_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}
_CLIENT_MODULES = {"requests", "httpx"}
_CLIENT_CTORS = {"Session", "Client", "AsyncClient"}  # requests.Session / httpx.Client


@cache
def _calls_query() -> str:
    return (_HERE / "calls.scm").read_text(encoding="utf-8")


@cache
def _clients_query() -> str:
    return (_HERE / "clients.scm").read_text(encoding="utf-8")


class HttpClientPack(FrameworkPack):
    name = "httpclient"
    language = "python"
    language_slug = "py"
    version = "2"  # ENH-020: instance clients + base_url composition
    dep_names = ("requests", "httpx")
    import_markers = ("import requests", "import httpx", "from requests", "from httpx")

    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        src = file.text.encode("utf-8")
        root = Parser(python_language()).parse(src).root_node
        prov = Provenance.parsed(f"pack:{self.name}@{self.version}", commit)
        facts = FrameworkFacts()
        # pass-1a: client instances (var -> framework + base_url)
        clients = self._client_vars(root, src)
        query = Query(python_language(), _calls_query())
        seen: set[str] = set()
        for _pattern, caps in QueryCursor(query).matches(root):
            obj_caps, method_caps, args_caps = caps.get("obj"), caps.get("method"), caps.get("args")
            if not (obj_caps and method_caps and args_caps):
                continue
            obj = text(obj_caps[0], src)
            # module-qualified (requests.get) OR a known client instance (s.get)
            if obj in _CLIENT_MODULES:
                framework, base_url = obj, ""
            elif obj in clients:
                framework, base_url = clients[obj]
            else:
                continue
            method = text(method_caps[0], src).lower()
            if method not in _HTTP_METHODS:
                continue
            arg = first_string_in(args_caps[0], src)
            if arg is None:
                facts.unresolved += 1  # dynamic URL — counted, never guessed
                continue
            url = _compose(base_url, arg)
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
                        "framework": framework,
                    },
                    provenance=prov,
                )
            )
        return facts

    def _client_vars(self, root: object, src: bytes) -> dict[str, tuple[str, str]]:
        """Variables bound to an HTTP client instance → ``(framework, base_url)``:
        ``c = httpx.Client(base_url="…")`` / ``s = requests.Session()``."""
        clients: dict[str, tuple[str, str]] = {}
        query = Query(python_language(), _clients_query())
        for _pattern, caps in QueryCursor(query).matches(root):  # type: ignore[arg-type]
            var, mod, ctor, args = (
                caps.get("var"),
                caps.get("mod"),
                caps.get("ctor"),
                caps.get("ctorargs"),
            )
            if not (var and mod and ctor and args):
                continue
            if text(mod[0], src) not in _CLIENT_MODULES or text(ctor[0], src) not in _CLIENT_CTORS:
                continue
            base_url = string_kwarg(args[0], "base_url", src) or ""
            clients[text(var[0], src)] = (text(mod[0], src), base_url)
        return clients


def _compose(base_url: str, arg: str) -> str:
    """Join a client ``base_url`` with a call argument. A bare path composes onto
    the base; an absolute URL passed despite a base_url wins (matches httpx)."""
    if not base_url or "://" in arg:
        return arg
    sep = "" if arg.startswith("/") else "/"
    return base_url.rstrip("/") + sep + arg


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
