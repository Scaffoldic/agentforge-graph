"""Spring pack golden tests (feat-011): controller route extraction, base-path
joining, @RequestMapping(method=…), HANDLED_BY to Class#method, the controller
guard, and the non-route negative."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentforge_graph.core import EdgeKind, NodeKind, SourceFile, SymbolID
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack
from agentforge_graph.frameworks.packs.spring import SPRING_PACK

FIXTURES = Path(__file__).parent / "fixtures" / "spring"


def _sf(name: str) -> SourceFile:
    raw = (FIXTURES / name).read_bytes()
    return SourceFile(
        path=name, text=raw.decode(), language="java", content_hash=hashlib.sha256(raw).hexdigest()
    )


def _src(text: str) -> SourceFile:
    return SourceFile(
        path="C.java",
        text=text,
        language="java",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def _facts() -> FrameworkFacts:
    return SPRING_PACK.extract(_sf("UserController.java"), repo="fixture", commit="c0")


def test_pack_is_a_framework_pack() -> None:
    assert isinstance(SPRING_PACK, FrameworkPack)
    assert SPRING_PACK.name == "spring"
    assert SPRING_PACK.language == "java" and SPRING_PACK.language_slug == "java"


def test_routes_extracted_with_base_path_joined() -> None:
    facts = _facts()
    routes = {n.name for n in facts.nodes if n.kind is NodeKind.ROUTE}
    assert routes == {
        "GET /api/users",
        "POST /api/users/{id}",
        "PUT /api/legacy",  # @RequestMapping(value=…, method=RequestMethod.PUT)
        "DELETE /api",  # @DeleteMapping with no path -> the base path
    }


def test_handled_by_targets_class_method() -> None:
    facts = _facts()
    handled = {(e.src, e.dst) for e in facts.edges if e.kind is EdgeKind.HANDLED_BY}
    create = next(n for n in facts.nodes if n.name == "POST /api/users/{id}")
    assert (create.id, create.attrs["handler"]) in handled
    assert SymbolID.parse(create.attrs["handler"]).descriptor == "UserController#create()."


def test_route_attrs() -> None:
    facts = _facts()
    get = next(n for n in facts.nodes if n.name == "GET /api/users")
    assert get.attrs["method"] == "GET"
    assert get.attrs["path"] == "/api/users"
    assert get.attrs["framework"] == "spring"


def test_non_controller_class_is_skipped() -> None:
    facts = SPRING_PACK.extract(_sf("Helper.java"), repo="fixture", commit="c0")
    assert facts.nodes == [] and facts.edges == []


def test_controller_without_base_path() -> None:
    facts = SPRING_PACK.extract(
        _src(
            "import org.springframework.web.bind.annotation.*;\n"
            "@RestController\n"
            "public class C {\n"
            '  @GetMapping("/ping")\n'
            '  public String ping() { return ""; }\n'
            "}\n"
        ),
        repo="fixture",
        commit="c0",
    )
    route = next(n for n in facts.nodes if n.kind is NodeKind.ROUTE)
    assert route.name == "GET /ping"


def test_no_routes_on_plain_file() -> None:
    facts = SPRING_PACK.extract(
        _src("public class C { public void f() {} }\n"), repo="fixture", commit="c0"
    )
    assert facts.nodes == [] and facts.edges == [] and facts.unresolved == 0
