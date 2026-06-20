"""FastAPI framework pack (feat-011) — routes + dependency injection.

Routes: ``@app.get("/x")`` / ``@router.post(...)`` decorators become ``Route``
nodes + ``HANDLED_BY`` edges to the handler ``Function``. DI: a parameter
defaulting to ``Depends(provider)`` / ``Security(provider)`` becomes a
``Service`` node (the provider) + an ``INJECTED_INTO`` edge to the consuming
function. Both are intra-file (decorator/param and the function share a file, so
the edge endpoints are in the file's ``FileSubgraph``). Class-based handlers /
consumers resolve to their ``Class#method`` symbol.

ENH-011 adds the cross-file pass-1 facts: each route carries ``router_var`` (its
``@app``/``@router`` object) and a ``path_pattern`` (initialised to the base
path), and each ``app.include_router(x.router, prefix="/api")`` becomes a
``RouteMount`` marker node. The generic pass-2 stitch
(``frameworks.cross_file``) composes prefixes onto the included router's routes
and grounds DI providers to their definition. A dynamic (non-literal) route path
or router ref is counted as unresolved, never guessed.
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
    callee_name,
    dotted_name,
    dotted_tail,
    enclosing_class,
    first_positional_arg,
    first_string_in,
    member_descriptor,
    python_language,
    string_kwarg,
    text,
)

_HERE = Path(__file__).parent
_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}
_DI_CALLS = {"Depends", "Security"}  # FastAPI dependency markers
_MOUNT_METHODS = {"include_router"}  # ENH-011 cross-file router mounts


@cache
def _routes_query() -> str:
    return (_HERE / "routes.scm").read_text(encoding="utf-8")


@cache
def _depends_query() -> str:
    return (_HERE / "depends.scm").read_text(encoding="utf-8")


@cache
def _include_query() -> str:
    return (_HERE / "include.scm").read_text(encoding="utf-8")


class FastAPIPack(FrameworkPack):
    name = "fastapi"
    language = "python"
    language_slug = "py"  # SymbolID slug — must match the Python language pack
    version = "1"
    dep_names = ("fastapi",)
    import_markers = ("import fastapi", "from fastapi")

    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        src = file.text.encode("utf-8")
        root = Parser(python_language()).parse(src).root_node
        prov = Provenance.parsed(f"pack:{self.name}@{self.version}", commit)
        facts = FrameworkFacts()
        self._extract_routes(root, src, repo, file, prov, facts)
        self._extract_depends(root, src, repo, file, prov, facts)
        self._extract_mounts(root, src, repo, file, prov, facts)
        return facts

    def _extract_routes(
        self,
        root: TSNode,
        src: bytes,
        repo: str,
        file: SourceFile,
        prov: Provenance,
        facts: FrameworkFacts,
    ) -> None:
        query = Query(python_language(), _routes_query())
        seen: set[str] = set()
        for _pattern, caps in QueryCursor(query).matches(root):
            method_caps = caps.get("method")
            handler_caps = caps.get("handler")
            args_caps = caps.get("args")
            if not (method_caps and handler_caps and args_caps):
                continue
            method = text(method_caps[0], src).lower()
            if method not in _HTTP_METHODS:
                continue  # @app.middleware / @app.on_event / etc. — not a route
            app_caps = caps.get("app")
            router_var = text(app_caps[0], src) if app_caps else ""

            # A route we recognise but can't pin down statically is counted,
            # not dropped: a dynamic (non-literal) path.
            path = first_string_in(args_caps[0], src)
            if path is None:
                facts.unresolved += 1
                continue

            handler = text(handler_caps[0], src)
            handler_desc = member_descriptor(handler, enclosing_class(handler_caps[0], src))
            handler_id = SymbolID.for_symbol(self.language_slug, repo, file.path, handler_desc)
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
                        # path_pattern is the cross-file composed path (ENH-011);
                        # pass-2 recomputes it from `path` + any router prefix.
                        # Initialised to the base path so an unmounted route is
                        # already correct and a backend without pass-2 still works.
                        "path_pattern": path,
                        "router_var": router_var,  # the @app/@router object name
                        "framework": self.name,
                        "handler": handler_id,
                    },
                    provenance=prov,
                )
            )
            facts.edges.append(
                Edge(src=route_id, dst=handler_id, kind=EdgeKind.HANDLED_BY, provenance=prov)
            )

    def _extract_depends(
        self,
        root: TSNode,
        src: bytes,
        repo: str,
        file: SourceFile,
        prov: Provenance,
        facts: FrameworkFacts,
    ) -> None:
        query = Query(python_language(), _depends_query())
        seen_service: set[str] = set()
        seen_edge: set[tuple[str, str]] = set()
        for _pattern, caps in QueryCursor(query).matches(root):
            fn_caps = caps.get("fn")
            name_caps = caps.get("func")
            if not (fn_caps and name_caps):
                continue
            fn_node = fn_caps[0]
            # MVP: only module-level functions (class-based consumers, like
            # class-based route handlers, are a follow-up) — counted, not dropped.
            params = fn_node.child_by_field_name("parameters")
            if params is None:
                continue
            providers = self._depends_providers(params, src)
            if not providers:
                continue
            consumer_desc = member_descriptor(
                text(name_caps[0], src), enclosing_class(name_caps[0], src)
            )
            consumer_id = SymbolID.for_symbol(self.language_slug, repo, file.path, consumer_desc)
            for provider in providers:
                service_id = SymbolID.for_symbol(
                    self.language_slug, repo, file.path, f"service({provider})."
                )
                if service_id not in seen_service:
                    seen_service.add(service_id)
                    facts.nodes.append(
                        GraphNode(
                            id=service_id,
                            kind=NodeKind.SERVICE,
                            name=provider,
                            span=(fn_node.start_point[0] + 1, fn_node.start_point[0] + 1),
                            attrs={"framework": self.name, "provider": provider},
                            provenance=prov,
                        )
                    )
                edge_key = (service_id, consumer_id)
                if edge_key not in seen_edge:
                    seen_edge.add(edge_key)
                    facts.edges.append(
                        Edge(
                            src=service_id,
                            dst=consumer_id,
                            kind=EdgeKind.INJECTED_INTO,
                            provenance=prov,
                        )
                    )

    def _extract_mounts(
        self,
        root: TSNode,
        src: bytes,
        repo: str,
        file: SourceFile,
        prov: Provenance,
        facts: FrameworkFacts,
    ) -> None:
        """ENH-011 pass-1: record each ``app.include_router(x.router,
        prefix="/api")`` as a ``RouteMount`` marker node. The node is file-owned
        (it rides this file's FileSubgraph) so it is cleared and re-emitted on
        re-parse; pass-2 reads markers + ``IMPORTS`` edges to compose prefixes
        onto the included router's routes. A dynamic mount (non-literal router
        ref) is counted as unresolved, never guessed."""
        query = Query(python_language(), _include_query())
        seen: set[str] = set()
        for _pattern, caps in QueryCursor(query).matches(root):
            method_caps = caps.get("method")
            args_caps = caps.get("args")
            if not (method_caps and args_caps):
                continue
            if text(method_caps[0], src) not in _MOUNT_METHODS:
                continue
            mount_node = caps["mount"][0]
            router_arg = first_positional_arg(mount_node, src)
            router_ref = dotted_name(router_arg, src) if router_arg is not None else ""
            if not router_ref:
                facts.unresolved += 1  # dynamic / non-literal router — counted
                continue
            prefix = string_kwarg(args_caps[0], "prefix", src) or ""
            line = mount_node.start_point[0] + 1
            mount_id = SymbolID.for_symbol(
                self.language_slug, repo, file.path, f"mount({router_ref}@{line})."
            )
            if mount_id in seen:
                continue
            seen.add(mount_id)
            facts.nodes.append(
                GraphNode(
                    id=mount_id,
                    kind=NodeKind.ROUTE_MOUNT,
                    name=router_ref,
                    span=(line, mount_node.end_point[0] + 1),
                    attrs={
                        "framework": self.name,
                        "router_ref": router_ref,  # as written: "payments.router"
                        # the included router's variable name in its own file —
                        # the last segment, matched against routes' router_var.
                        "router_var": router_ref.rsplit(".", 1)[-1],
                        "prefix": prefix,
                    },
                    provenance=prov,
                )
            )

    def _depends_providers(self, params: TSNode, src: bytes) -> list[str]:
        """Provider names from ``= Depends(provider)`` / ``= Security(provider)``
        parameter defaults, in source order (deduped)."""
        providers: list[str] = []
        for param in params.named_children:
            if param.type not in ("default_parameter", "typed_default_parameter"):
                continue
            value = param.child_by_field_name("value")
            if value is None or value.type != "call":
                continue
            if callee_name(value, src) not in _DI_CALLS:
                continue
            arg = first_positional_arg(value, src)
            provider = dotted_tail(arg, src) if arg is not None else ""
            if provider and provider not in providers:
                providers.append(provider)
        return providers


FASTAPI_PACK = FastAPIPack()
