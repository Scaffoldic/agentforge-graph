"""FastAPI pack golden tests (feat-011): route extraction, HANDLED_BY, and the
unresolved counter — asserted directly on FrameworkFacts."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentforge_graph.core import EdgeKind, NodeKind, SourceFile, SymbolID
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack
from agentforge_graph.frameworks.packs.fastapi import FASTAPI_PACK

FIXTURES = Path(__file__).parent / "fixtures" / "fastapi"


def _sf(name: str) -> SourceFile:
    raw = (FIXTURES / name).read_bytes()
    return SourceFile(
        path=name, text=raw.decode(), language="py", content_hash=hashlib.sha256(raw).hexdigest()
    )


def _facts() -> FrameworkFacts:
    return FASTAPI_PACK.extract(_sf("app.py"), repo="fixture", commit="c0")


def test_pack_is_a_framework_pack() -> None:
    assert isinstance(FASTAPI_PACK, FrameworkPack)
    assert FASTAPI_PACK.name == "fastapi"
    assert FASTAPI_PACK.language == "python" and FASTAPI_PACK.language_slug == "py"


def test_routes_extracted() -> None:
    facts = _facts()
    routes = {n.name: n for n in facts.nodes if n.kind is NodeKind.ROUTE}
    assert set(routes) == {"GET /health", "POST /payments/{pid}/refund"}
    health = routes["GET /health"]
    assert health.attrs["method"] == "GET"
    assert health.attrs["path"] == "/health"
    assert health.attrs["framework"] == "fastapi"
    assert health.span is not None and health.span[0] >= 1


def test_handled_by_targets_the_handler_function() -> None:
    facts = _facts()
    handled = {(e.src, e.dst) for e in facts.edges if e.kind is EdgeKind.HANDLED_BY}
    routes = {n.id: n for n in facts.nodes if n.kind is NodeKind.ROUTE}
    # every HANDLED_BY goes route -> the handler symbol id recorded in attrs
    for src, dst in handled:
        assert routes[src].attrs["handler"] == dst
    refund = next(n for n in facts.nodes if n.name == "POST /payments/{pid}/refund")
    assert SymbolID.parse(refund.attrs["handler"]).descriptor == "refund()."


def test_unresolved_counts_dynamic_path_not_middleware() -> None:
    facts = _facts()
    # the PREFIX + "/dynamic" route is counted; @app.middleware is not a route
    assert facts.unresolved == 1


def test_class_method_handler_resolves_to_class_method() -> None:
    text = (
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n\n"
        "class Views:\n"
        "    @app.get('/m')\n"
        "    def handler(self):\n"
        "        return 1\n"
    )
    sf = SourceFile(
        path="v.py",
        text=text,
        language="py",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    facts = FASTAPI_PACK.extract(sf, repo="fixture", commit="c0")
    route = next(n for n in facts.nodes if n.kind is NodeKind.ROUTE)
    assert route.name == "GET /m"
    assert facts.unresolved == 0  # class-based handler now resolves
    # HANDLED_BY targets the Views#handler method symbol
    assert SymbolID.parse(route.attrs["handler"]).descriptor == "Views#handler()."


def _src(text: str) -> SourceFile:
    return SourceFile(
        path="d.py",
        text=text,
        language="py",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def test_depends_creates_service_and_injected_into() -> None:
    facts = _facts()
    services = {n.name: n for n in facts.nodes if n.kind is NodeKind.SERVICE}
    assert "get_db" in services
    assert services["get_db"].attrs["provider"] == "get_db"
    injected = {(e.src, e.dst) for e in facts.edges if e.kind is EdgeKind.INJECTED_INTO}
    refund = SymbolID.for_symbol("py", "fixture", "app.py", "refund().")
    assert (services["get_db"].id, refund) in injected


def test_security_and_typed_depends_recognised() -> None:
    facts = FASTAPI_PACK.extract(
        _src(
            "from fastapi import Depends, Security\n\n"
            "def h(a = Depends(dep_a), b: User = Security(dep_b)):\n"
            "    return 1\n"
        ),
        repo="fixture",
        commit="c0",
    )
    services = {n.name for n in facts.nodes if n.kind is NodeKind.SERVICE}
    assert services == {"dep_a", "dep_b"}


def test_class_based_consumer_resolves_to_class_method() -> None:
    facts = FASTAPI_PACK.extract(
        _src(
            "from fastapi import Depends\n\n"
            "class V:\n"
            "    def h(self, db = Depends(get_db)):\n"
            "        return 1\n"
        ),
        repo="fixture",
        commit="c0",
    )
    service = next(n for n in facts.nodes if n.kind is NodeKind.SERVICE)
    injected = next(e for e in facts.edges if e.kind is EdgeKind.INJECTED_INTO)
    assert injected.src == service.id
    assert SymbolID.parse(injected.dst).descriptor == "V#h()."
    assert facts.unresolved == 0  # class-based consumer now resolves


def test_no_services_without_depends() -> None:
    facts = FASTAPI_PACK.extract(
        _src("def plain(a, b=1):\n    return a + b\n"), repo="fixture", commit="c0"
    )
    assert [n for n in facts.nodes if n.kind is NodeKind.SERVICE] == []


def test_no_routes_on_plain_file() -> None:
    text = "def helper():\n    return 1\n"
    sf = SourceFile(
        path="p.py",
        text=text,
        language="py",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    facts = FASTAPI_PACK.extract(sf, repo="fixture", commit="c0")
    assert facts.nodes == [] and facts.edges == [] and facts.unresolved == 0


# --- ENH-011 pass-1: router_var, path_pattern, mount markers ----------------


def test_routes_carry_router_var_and_path_pattern() -> None:
    facts = FASTAPI_PACK.extract(
        _src(
            "from fastapi import APIRouter\n"
            "router = APIRouter()\n"
            '@router.get("/charge")\n'
            "def charge():\n    return {}\n"
        ),
        repo="fixture",
        commit="c0",
    )
    route = next(n for n in facts.nodes if n.kind is NodeKind.ROUTE)
    assert route.attrs["router_var"] == "router"  # the @router object
    # path_pattern starts equal to the base path (pass-2 may compose a prefix).
    assert route.attrs["path"] == "/charge"
    assert route.attrs["path_pattern"] == "/charge"


def test_include_router_emits_mount_marker() -> None:
    facts = FASTAPI_PACK.extract(
        _src(
            "from fastapi import FastAPI\n"
            "from .payments import routes\n"
            "app = FastAPI()\n"
            'app.include_router(routes.router, prefix="/api")\n'
        ),
        repo="fixture",
        commit="c0",
    )
    mount = next(n for n in facts.nodes if n.kind is NodeKind.ROUTE_MOUNT)
    assert mount.attrs["router_ref"] == "routes.router"
    assert mount.attrs["router_var"] == "router"  # the included router's var name
    assert mount.attrs["prefix"] == "/api"


def test_dynamic_mount_is_counted_not_guessed() -> None:
    # a non-literal router ref (a subscript) can't be tied to a router var → it
    # is counted as unresolved, never mis-resolved (ADR-0004).
    facts = FASTAPI_PACK.extract(
        _src(
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            'app.include_router(registry[name], prefix="/api")\n'
        ),
        repo="fixture",
        commit="c0",
    )
    assert [n for n in facts.nodes if n.kind is NodeKind.ROUTE_MOUNT] == []
    assert facts.unresolved == 1
