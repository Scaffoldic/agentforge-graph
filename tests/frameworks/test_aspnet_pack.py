"""ASP.NET pack golden tests (ENH-012): attribute-routed controllers, the
[controller] token, HANDLED_BY to Class#method, and conservative controller
detection — asserted directly on FrameworkFacts."""

from __future__ import annotations

import hashlib

from agentforge_graph.core import EdgeKind, NodeKind, SourceFile, SymbolID
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack
from agentforge_graph.frameworks.packs.aspnet import ASPNET_PACK


def _src(text: str) -> SourceFile:
    return SourceFile(
        path="Api.cs",
        text=text,
        language="cs",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def _facts(text: str) -> FrameworkFacts:
    return ASPNET_PACK.extract(_src(text), repo="fixture", commit="c0")


_CONTROLLER = (
    "[ApiController]\n"
    '[Route("api/[controller]")]\n'
    "public class UsersController : ControllerBase {\n"
    '    [HttpGet("{id}")]\n'
    "    public IActionResult Get(int id) { return Ok(); }\n"
    "    [HttpPost]\n"
    "    public IActionResult Create() { return Ok(); }\n"
    "}\n"
)


def test_pack_is_a_framework_pack() -> None:
    assert isinstance(ASPNET_PACK, FrameworkPack)
    assert ASPNET_PACK.name == "aspnet"
    assert ASPNET_PACK.language == "csharp" and ASPNET_PACK.language_slug == "cs"


def test_detect_via_import_marker() -> None:
    assert ASPNET_PACK.detect(set(), "using Microsoft.AspNetCore.Mvc;") is True
    assert ASPNET_PACK.detect(set(), "class Plain {}") is False


def test_routes_with_base_and_controller_token() -> None:
    routes = {n.name: n for n in _facts(_CONTROLLER).nodes if n.kind is NodeKind.ROUTE}
    # [controller] -> Users; base path joined with method path.
    assert set(routes) == {"GET /api/Users/{id}", "POST /api/Users"}
    get = routes["GET /api/Users/{id}"]
    assert get.attrs["method"] == "GET" and get.attrs["framework"] == "aspnet"
    assert get.attrs["path_pattern"] == "/api/Users/{id}"


def test_handled_by_targets_class_method() -> None:
    facts = _facts(_CONTROLLER)
    get = next(n for n in facts.nodes if n.name == "GET /api/Users/{id}")
    edge = next(e for e in facts.edges if e.kind is EdgeKind.HANDLED_BY and e.src == get.id)
    assert SymbolID.parse(edge.dst).descriptor == "UsersController#Get()."
    assert get.attrs["handler"] == edge.dst


def test_plain_class_is_not_a_route_source() -> None:
    facts = _facts(
        "public class EmailService {\n"
        '    [HttpGet("/x")]\n'  # an HttpGet on a non-controller is ignored
        "    public void Send() { }\n"
        "}\n"
    )
    assert [n for n in facts.nodes if n.kind is NodeKind.ROUTE] == []


def test_controller_by_base_without_attributes() -> None:
    # a class with a ControllerBase base is a controller even without [ApiController]
    facts = _facts(
        "public class HomeController : Controller {\n"
        '    [HttpGet("/home")]\n'
        "    public IActionResult Index() { return Ok(); }\n"
        "}\n"
    )
    routes = [n for n in facts.nodes if n.kind is NodeKind.ROUTE]
    assert len(routes) == 1 and routes[0].name == "GET /home"
