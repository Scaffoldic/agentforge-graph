"""Gin pack golden tests (ENH-012): route extraction, HANDLED_BY, router_var /
path_pattern, and the unresolved counter — asserted directly on FrameworkFacts."""

from __future__ import annotations

import hashlib

from agentforge_graph.core import EdgeKind, NodeKind, SourceFile, SymbolID
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack
from agentforge_graph.frameworks.packs.gin import GIN_PACK


def _src(text: str) -> SourceFile:
    return SourceFile(
        path="main.go",
        text=text,
        language="go",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def _facts(text: str) -> FrameworkFacts:
    return GIN_PACK.extract(_src(text), repo="fixture", commit="c0")


def test_pack_is_a_framework_pack() -> None:
    assert isinstance(GIN_PACK, FrameworkPack)
    assert GIN_PACK.name == "gin"
    assert GIN_PACK.language == "go" and GIN_PACK.language_slug == "go"


def test_detect_via_import_marker() -> None:
    # Go deps live in go.mod (not scanned) — detection rides the import marker.
    assert GIN_PACK.detect(set(), 'import "github.com/gin-gonic/gin"') is True
    assert GIN_PACK.detect(set(), "package main") is False


def test_routes_extracted_with_method_and_path() -> None:
    facts = _facts(
        "package main\n"
        "func ping(c *gin.Context) {}\n"
        "func main() {\n"
        "\tr := gin.Default()\n"
        '\tr.GET("/ping", ping)\n'
        '\tr.POST("/users", ping)\n'
        "}\n"
    )
    routes = {n.name: n for n in facts.nodes if n.kind is NodeKind.ROUTE}
    assert set(routes) == {"GET /ping", "POST /users"}
    ping = routes["GET /ping"]
    assert ping.attrs["method"] == "GET"
    assert ping.attrs["path"] == "/ping"
    assert ping.attrs["path_pattern"] == "/ping"  # ENH-011 forward-compat
    assert ping.attrs["router_var"] == "r"
    assert ping.attrs["framework"] == "gin"


def test_handled_by_targets_named_handler_symbol() -> None:
    facts = _facts(
        "package main\n"
        "func ping(c *gin.Context) {}\n"
        "func main() {\n"
        "\tr := gin.Default()\n"
        '\tr.GET("/ping", ping)\n'
        "}\n"
    )
    route = next(n for n in facts.nodes if n.kind is NodeKind.ROUTE)
    edge = next(e for e in facts.edges if e.kind is EdgeKind.HANDLED_BY)
    assert edge.src == route.id
    # the edge points at the Go function symbol id for `ping`
    assert SymbolID.parse(edge.dst).descriptor == "ping()."
    assert route.attrs["handler"] == edge.dst


def test_anonymous_handler_yields_route_without_edge() -> None:
    facts = _facts(
        "package main\n"
        "func main() {\n"
        "\tr := gin.Default()\n"
        '\tr.DELETE("/users/:id", func(c *gin.Context) {})\n'
        "}\n"
    )
    route = next(n for n in facts.nodes if n.kind is NodeKind.ROUTE)
    assert route.attrs["handler"] == ""  # no symbol to point at
    assert [e for e in facts.edges if e.kind is EdgeKind.HANDLED_BY] == []


def test_dynamic_path_counted_not_dropped() -> None:
    facts = _facts(
        'package main\nfunc main() {\n\tr := gin.Default()\n\tr.GET("/dyn"+x, ping)\n}\n'
    )
    assert [n for n in facts.nodes if n.kind is NodeKind.ROUTE] == []
    assert facts.unresolved == 1


def test_non_route_calls_ignored() -> None:
    facts = _facts(
        "package main\n"
        "func main() {\n"
        "\tr := gin.Default()\n"
        '\tv := r.Group("/api")\n'
        "\tr.Use(mw)\n"
        "\tr.Run()\n"
        "\t_ = v\n"
        "}\n"
    )
    # gin.Default()/Group/Use/Run are not HTTP verbs → no routes, nothing counted.
    assert [n for n in facts.nodes if n.kind is NodeKind.ROUTE] == []
    assert facts.unresolved == 0
