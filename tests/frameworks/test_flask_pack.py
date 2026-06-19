"""Flask pack golden tests (feat-011): route extraction (incl. methods= list and
2.0 shortcuts), HANDLED_BY, the non-route guard, and the unresolved counter."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentforge_graph.core import EdgeKind, NodeKind, SourceFile, SymbolID
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack
from agentforge_graph.frameworks.packs.flask import FLASK_PACK

FIXTURES = Path(__file__).parent / "fixtures" / "flask"


def _sf(name: str) -> SourceFile:
    raw = (FIXTURES / name).read_bytes()
    return SourceFile(
        path=name, text=raw.decode(), language="py", content_hash=hashlib.sha256(raw).hexdigest()
    )


def _src(text: str) -> SourceFile:
    return SourceFile(
        path="m.py",
        text=text,
        language="py",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def _facts() -> FrameworkFacts:
    return FLASK_PACK.extract(_sf("app.py"), repo="fixture", commit="c0")


def test_pack_is_a_framework_pack() -> None:
    assert isinstance(FLASK_PACK, FrameworkPack)
    assert FLASK_PACK.name == "flask"
    assert FLASK_PACK.language == "python" and FLASK_PACK.language_slug == "py"


def test_routes_extracted_with_methods_and_shortcuts() -> None:
    facts = _facts()
    routes = {n.name for n in facts.nodes if n.kind is NodeKind.ROUTE}
    assert routes == {
        "GET /health",
        "GET /users/<int:uid>",  # methods=["GET","POST"] -> one route per method
        "POST /users/<int:uid>",
        "GET /items",  # @bp.get shortcut
    }


def test_route_default_method_is_get() -> None:
    facts = _facts()
    health = next(n for n in facts.nodes if n.name == "GET /health")
    assert health.attrs["method"] == "GET"
    assert health.attrs["framework"] == "flask"


def test_handled_by_targets_handler() -> None:
    facts = _facts()
    user_routes = [n for n in facts.nodes if "users" in n.name]
    handled = {(e.src, e.dst) for e in facts.edges if e.kind is EdgeKind.HANDLED_BY}
    for r in user_routes:
        assert (r.id, r.attrs["handler"]) in handled
        assert SymbolID.parse(r.attrs["handler"]).descriptor == "user()."


def test_dynamic_path_counted_unresolved() -> None:
    # PREFIX + "/dynamic" is non-literal; @app.before_request is not a route at all
    assert _facts().unresolved == 1


def test_class_based_handler_resolves_to_method() -> None:
    facts = FLASK_PACK.extract(
        _src(
            "from flask import Blueprint\n\n"
            "bp = Blueprint('a', __name__)\n\n"
            "class View:\n"
            "    @bp.route('/m')\n"
            "    def handle(self):\n"
            "        return 1\n"
        ),
        repo="fixture",
        commit="c0",
    )
    route = next(n for n in facts.nodes if n.kind is NodeKind.ROUTE)
    assert SymbolID.parse(route.attrs["handler"]).descriptor == "View#handle()."


def test_no_routes_on_plain_file() -> None:
    facts = FLASK_PACK.extract(_src("def f():\n    return 1\n"), repo="fixture", commit="c0")
    assert facts.nodes == [] and facts.edges == [] and facts.unresolved == 0
