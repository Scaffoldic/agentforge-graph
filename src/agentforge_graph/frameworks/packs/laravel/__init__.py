"""Laravel framework pack (ENH-012) — routes (PHP).

Extracts the ``Route::get('/x', [C::class, 'm'])`` static-DSL into ``Route``
nodes. The handler reference names a controller that lives in **another file**,
so the pack records ``handler_class`` / ``handler_method`` on the route and the
generic cross-file pass-2 (``frameworks.cross_file``) grounds them to the real
``Class#method`` symbol (``HANDLED_BY``). Three handler shapes are recognised:
``[UserController::class, 'index']``, the string ``'UserController@index'``, and
an invokable ``[InvokableController::class]`` / ``'InvokableController'`` (→
``__invoke``). A closure handler yields the ``Route`` (the API surface) with no
controller reference; a dynamic (non-literal) path is counted as unresolved.
Eloquent models are a follow-up.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from tree_sitter import Node as TSNode
from tree_sitter import Parser, Query, QueryCursor

from agentforge_graph.core import Node as GraphNode
from agentforge_graph.core import (
    NodeKind,
    Provenance,
    SourceFile,
    SymbolID,
)
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack
from agentforge_graph.frameworks.packs._php_ast import (
    arg_value,
    php_language,
    string_value,
    text,
)

_HERE = Path(__file__).parent
_VERBS = {"get", "post", "put", "patch", "delete", "options", "any"}


@cache
def _query_text() -> str:
    return (_HERE / "routes.scm").read_text(encoding="utf-8")


class LaravelPack(FrameworkPack):
    name = "laravel"
    language = "php"
    language_slug = "php"  # SymbolID slug — must match the PHP language pack
    version = "1"
    dep_names = ()  # PHP deps live in composer.json (not scanned); rely on markers
    import_markers = ("Illuminate\\", "use Illuminate")

    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        src = file.text.encode("utf-8")
        lang = php_language()
        root = Parser(lang).parse(src).root_node
        query = Query(lang, _query_text())
        prov = Provenance.parsed(f"pack:{self.name}@{self.version}", commit)
        facts = FrameworkFacts()
        seen: set[str] = set()

        for _pattern, caps in QueryCursor(query).matches(root):
            facade_caps = caps.get("facade")
            method_caps = caps.get("method")
            args_caps = caps.get("args")
            call_caps = caps.get("call")
            if not (facade_caps and method_caps and args_caps and call_caps):
                continue
            if text(facade_caps[0], src) != "Route":
                continue  # only the Route facade
            verb = text(method_caps[0], src).lower()
            if verb not in _VERBS:
                continue  # Route::middleware / group / name / … — not an endpoint

            args = [a for a in args_caps[0].named_children if a.type == "argument"]
            if not args:
                continue
            path = string_value(arg_value(args[0]), src)
            if path is None:
                facts.unresolved += 1  # dynamic / non-literal path
                continue

            handler_class, handler_method = self._handler(args, src)
            method_u = "ALL" if verb == "any" else verb.upper()
            route_id = SymbolID.for_symbol(
                self.language_slug, repo, file.path, f"route({method_u} {path})."
            )
            if route_id in seen:
                continue
            seen.add(route_id)
            call = call_caps[0]
            facts.nodes.append(
                GraphNode(
                    id=route_id,
                    kind=NodeKind.ROUTE,
                    name=f"{method_u} {path}",
                    span=(call.start_point[0] + 1, call.end_point[0] + 1),
                    attrs={
                        "method": method_u,
                        "path": path,
                        "path_pattern": path,
                        "framework": self.name,
                        "handler": "",  # grounded cross-file by pass-2
                        "handler_class": handler_class,
                        "handler_method": handler_method,
                    },
                    provenance=prov,
                )
            )
        return facts

    def _handler(self, args: list[TSNode], src: bytes) -> tuple[str, str]:
        """``(controller_class, method)`` from the 2nd argument, or ``("", "")``
        for a closure / unrecognised handler. Recognises ``[C::class, 'm']``,
        ``'C@m'`` and the invokable ``[C::class]`` / ``'C'`` (→ ``__invoke``)."""
        if len(args) < 2:
            return "", ""
        value = arg_value(args[1])
        if value.type == "array_creation_expression":
            return self._handler_from_array(value, src)
        if value.type == "class_constant_access_expression":
            # an invokable single-action controller: Route::get('/x', Clock::class)
            return self._class_const_name(value, src), "__invoke"
        s = string_value(value, src)
        if s is not None:
            if "@" in s:
                cls, _, meth = s.partition("@")
                return cls.rsplit("\\", 1)[-1], meth
            return s.rsplit("\\", 1)[-1], "__invoke"  # invokable controller string
        return "", ""

    def _handler_from_array(self, array: TSNode, src: bytes) -> tuple[str, str]:
        elems = [e for e in array.named_children if e.type == "array_element_initializer"]
        if not elems:
            return "", ""
        cls = self._class_const_name(arg_value(elems[0]), src)
        if not cls:
            return "", ""
        method = "__invoke"
        if len(elems) >= 2:
            m = string_value(arg_value(elems[1]), src)
            method = m if m is not None else "__invoke"
        return cls, method

    def _class_const_name(self, node: TSNode, src: bytes) -> str:
        """``UserController`` from a ``UserController::class`` access (the leading
        name, namespace-stripped); "" for anything else."""
        if node.type != "class_constant_access_expression" or not node.named_children:
            return ""
        return text(node.named_children[0], src).rsplit("\\", 1)[-1]


LARAVEL_PACK = LaravelPack()
