"""Express pack golden tests (feat-011): route extraction across JS/TS, named vs
anonymous handlers, the non-route guard, and the dynamic-path unresolved count."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentforge_graph.core import EdgeKind, NodeKind, SourceFile, SymbolID
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack
from agentforge_graph.frameworks.packs.express import EXPRESS_PACK

FIXTURES = Path(__file__).parent / "fixtures" / "express"


def _sf(name: str, language: str = "js") -> SourceFile:
    raw = (FIXTURES / name).read_bytes()
    return SourceFile(
        path=name,
        text=raw.decode(),
        language=language,
        content_hash=hashlib.sha256(raw).hexdigest(),
    )


def _src(text: str, language: str = "js") -> SourceFile:
    name = "m.ts" if language == "ts" else "m.js"
    return SourceFile(
        path=name,
        text=text,
        language=language,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def _facts() -> FrameworkFacts:
    return EXPRESS_PACK.extract(_sf("app.js"), repo="fixture", commit="c0")


def test_pack_spans_js_and_ts() -> None:
    assert isinstance(EXPRESS_PACK, FrameworkPack)
    assert EXPRESS_PACK.name == "express"
    assert set(EXPRESS_PACK.slugs) == {"js", "ts"}


def test_routes_extracted() -> None:
    facts = _facts()
    routes = {n.name for n in facts.nodes if n.kind is NodeKind.ROUTE}
    assert routes == {"GET /users", "POST /items", "GET /health"}


def test_named_handler_gets_handled_by_edge() -> None:
    facts = _facts()
    handled = {(e.src, e.dst) for e in facts.edges if e.kind is EdgeKind.HANDLED_BY}
    users = next(n for n in facts.nodes if n.name == "GET /users")
    assert (users.id, users.attrs["handler"]) in handled
    assert SymbolID.parse(users.attrs["handler"]).descriptor == "getUsers()."


def test_anonymous_handler_yields_route_without_edge() -> None:
    facts = _facts()
    items = next(n for n in facts.nodes if n.name == "POST /items")
    assert items.attrs["handler"] == ""  # inline arrow -> no symbol to point at
    assert not any(e.kind is EdgeKind.HANDLED_BY and e.src == items.id for e in facts.edges)


def test_use_and_listen_and_dynamic_path() -> None:
    facts = _facts()
    # app.use (mount) + app.listen are not route methods; app.get(buildPath())
    # is a dynamic path -> exactly one unresolved
    assert facts.unresolved == 1


def test_typescript_route_uses_ts_slug() -> None:
    facts = EXPRESS_PACK.extract(
        _src("const r = express.Router();\nr.get('/t', handler);\n", language="ts"),
        repo="fixture",
        commit="c0",
    )
    route = next(n for n in facts.nodes if n.kind is NodeKind.ROUTE)
    assert SymbolID.parse(route.attrs["handler"]).lang == "ts"


def test_no_routes_on_plain_file() -> None:
    facts = EXPRESS_PACK.extract(_src("function f(){ return 1; }\n"), repo="fixture", commit="c0")
    assert facts.nodes == [] and facts.edges == [] and facts.unresolved == 0
