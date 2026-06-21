"""JS/TS HTTP-client pack (ENH-020 C-full) — outbound cross-service calls.

Captures ``fetch("…")``, ``axios.get("…")`` / ``axios.post("…")`` and
``axios("…")`` as ``ServiceCall`` nodes (the JS/TS counterpart of the Python
``httpclient`` pack). For ``fetch`` the method is read from a literal
``{ method: "POST" }`` option object, defaulting to ``GET``.

Spans ``.js`` and ``.ts`` (Express-style). Conservative (ADR-0004): literal URLs
only; a computed/templated URL is counted as unresolved, never guessed. Reuses
the shared ``_url_path`` URL helper. Zero ``agentforge`` imports (ADR-0001).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from tree_sitter import Node as TSNode
from tree_sitter import Parser, Query, QueryCursor

from agentforge_graph.core import Node as GraphNode
from agentforge_graph.core import NodeKind, Provenance, SourceFile, SymbolID
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack
from agentforge_graph.frameworks.packs._js_ast import (
    first_arg_string,
    js_language,
    strip_quotes,
    text,
)
from agentforge_graph.frameworks.packs.httpclient import _url_path

_HERE = Path(__file__).parent
_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}


@cache
def _calls_query() -> str:
    return (_HERE / "calls.scm").read_text(encoding="utf-8")


class JsHttpClientPack(FrameworkPack):
    name = "jshttpclient"
    language = "javascript/typescript"
    language_slug = "js"
    version = "1"
    dep_names = ("axios",)
    import_markers = ("axios", "fetch(")

    @property
    def slugs(self) -> tuple[str, ...]:
        return ("js", "ts")

    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        slug = file.language  # "js" or "ts"
        src = file.text.encode("utf-8")
        lang = js_language(slug)
        root = Parser(lang).parse(src).root_node
        prov = Provenance.parsed(f"pack:{self.name}@{self.version}", commit)
        facts = FrameworkFacts()
        seen: set[str] = set()
        for _pattern, caps in QueryCursor(Query(lang, _calls_query())).matches(root):
            args_caps = caps.get("args")
            if not args_caps:
                continue
            framework, method = self._client_call(caps, args_caps[0], src)
            if framework is None:
                continue
            url = first_arg_string(args_caps[0], src)
            if url is None:
                facts.unresolved += 1  # dynamic URL — counted, never guessed
                continue
            call_node = caps["call"][0]
            line = call_node.start_point[0] + 1
            call_id = SymbolID.for_symbol(
                slug, repo, file.path, f"servicecall({method} {url}@{line})."
            )
            if call_id in seen:
                continue
            seen.add(call_id)
            facts.nodes.append(
                GraphNode(
                    id=call_id,
                    kind=NodeKind.SERVICE_CALL,
                    name=f"{method} {url}",
                    span=(line, call_node.end_point[0] + 1),
                    attrs={
                        "method": method,
                        "url": url,
                        "path": _url_path(url),
                        "framework": framework,
                    },
                    provenance=prov,
                )
            )
        return facts

    def _client_call(
        self, caps: dict[str, list[TSNode]], args: TSNode, src: bytes
    ) -> tuple[str | None, str]:
        """``(framework, METHOD)`` for a recognised client call, else ``(None, "")``."""
        if caps.get("obj"):  # axios.get(...) / axios.post(...)
            if text(caps["obj"][0], src) != "axios":
                return None, ""
            method = text(caps["method"][0], src).lower()
            return ("axios", method.upper()) if method in _HTTP_METHODS else (None, "")
        fn_caps = caps.get("fn")  # fetch(...) / axios(...)
        if not fn_caps:
            return None, ""
        fn = text(fn_caps[0], src)
        if fn == "fetch":
            return "fetch", _fetch_method(args, src)
        if fn == "axios":
            return "axios", "GET"
        return None, ""


def _fetch_method(args: TSNode, src: bytes) -> str:
    """The HTTP method from ``fetch(url, { method: "POST" })`` when literal, else
    ``GET`` (fetch's default)."""
    kids = args.named_children
    if len(kids) < 2 or kids[1].type != "object":
        return "GET"
    for pair in kids[1].named_children:
        if pair.type != "pair":
            continue
        key, value = pair.child_by_field_name("key"), pair.child_by_field_name("value")
        if (
            key is not None
            and strip_quotes(text(key, src)) == "method"
            and value is not None
            and value.type == "string"
        ):
            return strip_quotes(text(value, src)).upper()
    return "GET"


JSHTTPCLIENT_PACK = JsHttpClientPack()
