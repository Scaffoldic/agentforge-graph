"""Rails framework pack (ENH-012) — routes.rb (Ruby).

Rails routing is a config DSL, not declarations on the handler, so this pack
interprets the ``Rails.application.routes.draw do … end`` block. It recognises
the **explicit** declarations first (the spec's MVP scope):

* ``get "/users" => "users#index"``
* ``post "/users", to: "users#create"``
* ``root "home#index"`` (→ ``GET /``)

Each becomes a ``Route`` carrying ``handler_class`` (the controller, camelized +
``Controller``) / ``handler_method`` (the action); the controller lives in
another file, so the generic cross-file pass-2 (``frameworks.cross_file``)
grounds it to the real ``Class#method`` symbol (``HANDLED_BY``). The resourceful
``resources :photos`` shorthand and ``namespace``/``scope`` nesting are
follow-ups (counted, not expanded); ActiveRecord models are a follow-up too.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from tree_sitter import Node as TSNode
from tree_sitter import Parser, Query, QueryCursor

from agentforge_graph.core import Node as GraphNode
from agentforge_graph.core import NodeKind, Provenance, SourceFile, SymbolID
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack
from agentforge_graph.frameworks.packs._ruby_ast import (
    camelize,
    ruby_language,
    ruby_string,
    text,
)

_HERE = Path(__file__).parent
_VERBS = {"get", "post", "put", "patch", "delete"}
_NESTING = {"resources", "resource", "namespace", "scope", "member", "collection"}


@cache
def _query_text() -> str:
    return (_HERE / "routes.scm").read_text(encoding="utf-8")


class RailsPack(FrameworkPack):
    name = "rails"
    language = "ruby"
    language_slug = "rb"  # SymbolID slug — must match the Ruby language pack
    version = "1"
    dep_names = ()  # Ruby deps live in the Gemfile (not scanned); rely on markers
    import_markers = ("Rails.application.routes", "ActionController", "Rails.application")

    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        src = file.text.encode("utf-8")
        lang = ruby_language()
        root = Parser(lang).parse(src).root_node
        query = Query(lang, _query_text())
        prov = Provenance.parsed(f"pack:{self.name}@{self.version}", commit)
        facts = FrameworkFacts()
        seen: set[str] = set()

        for _pattern, caps in QueryCursor(query).matches(root):
            draw_caps = caps.get("draw")
            block_caps = caps.get("block")
            if not (draw_caps and block_caps):
                continue
            if text(draw_caps[0], src) != "draw":
                continue  # only the routes.draw block
            self._walk_block(block_caps[0], src, repo, file, prov, facts, seen)
        return facts

    def _walk_block(
        self,
        block: TSNode,
        src: bytes,
        repo: str,
        file: SourceFile,
        prov: Provenance,
        facts: FrameworkFacts,
        seen: set[str],
    ) -> None:
        """Find route-verb calls anywhere inside the draw block."""
        for node in self._iter_calls(block):
            method_node = node.child_by_field_name("method")
            if method_node is None:
                continue
            verb = text(method_node, src)
            args = node.child_by_field_name("arguments")
            if verb == "root":
                self._emit_root(args, src, repo, file, prov, facts, seen)
            elif verb in _VERBS:
                self._emit_verb(verb, args, src, repo, file, prov, facts, seen)
            elif verb in _NESTING:
                facts.unresolved += 1  # resourceful/nested DSL — counted, not expanded

    def _iter_calls(self, node: TSNode) -> list[TSNode]:
        out: list[TSNode] = []
        for c in node.named_children:
            if c.type in ("call", "command"):
                out.append(c)
            out.extend(self._iter_calls(c))
        return out

    def _emit_verb(
        self,
        verb: str,
        args: TSNode | None,
        src: bytes,
        repo: str,
        file: SourceFile,
        prov: Provenance,
        facts: FrameworkFacts,
        seen: set[str],
    ) -> None:
        if args is None:
            return
        path, handler = self._path_and_handler(args, src)
        if path is None or handler is None:
            return
        self._emit(verb.upper(), path, handler, args, src, repo, file, prov, facts, seen)

    def _emit_root(
        self,
        args: TSNode | None,
        src: bytes,
        repo: str,
        file: SourceFile,
        prov: Provenance,
        facts: FrameworkFacts,
        seen: set[str],
    ) -> None:
        if args is None:
            return
        handler = None
        for child in args.named_children:
            if child.type == "string":
                handler = ruby_string(child, src)
                break
            if child.type == "pair":
                handler = self._pair_value(child, src, "to")
        if handler:
            self._emit("GET", "/", handler, args, src, repo, file, prov, facts, seen)

    def _path_and_handler(self, args: TSNode, src: bytes) -> tuple[str | None, str | None]:
        """``(path, "controller#action")`` for the two explicit forms; a missing
        piece yields None (the call is skipped)."""
        path: str | None = None
        handler: str | None = None
        for child in args.named_children:
            if child.type == "string" and path is None:
                path = ruby_string(child, src)
            elif child.type == "pair":
                key = child.child_by_field_name("key")
                value = child.child_by_field_name("value")
                if key is None or value is None:
                    continue
                if key.type == "string":  # "/x" => "c#a"
                    path = ruby_string(key, src)
                    handler = ruby_string(value, src)
                elif text(key, src) in ("to",):  # , to: "c#a"
                    handler = ruby_string(value, src)
        return path, handler

    def _pair_value(self, pair: TSNode, src: bytes, key_name: str) -> str | None:
        key = pair.child_by_field_name("key")
        value = pair.child_by_field_name("value")
        if key is None or value is None or text(key, src) != key_name:
            return None
        return ruby_string(value, src)

    def _emit(
        self,
        method: str,
        path: str,
        handler: str,
        anchor: TSNode,
        src: bytes,
        repo: str,
        file: SourceFile,
        prov: Provenance,
        facts: FrameworkFacts,
        seen: set[str],
    ) -> None:
        if "#" not in handler:
            return  # not a controller#action mapping
        controller, _, action = handler.partition("#")
        # Rails maps "admin/users" -> Admin::UsersController; the Ruby class node
        # is named by the last segment, so match on that (camelized + Controller).
        handler_class = camelize(controller.rsplit("/", 1)[-1]) + "Controller"
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
                span=(anchor.start_point[0] + 1, anchor.end_point[0] + 1),
                attrs={
                    "method": method,
                    "path": path,
                    "path_pattern": path,
                    "framework": self.name,
                    "handler": "",  # grounded cross-file by pass-2
                    "handler_class": handler_class,
                    "handler_method": action,
                },
                provenance=prov,
            )
        )


RAILS_PACK = RailsPack()
