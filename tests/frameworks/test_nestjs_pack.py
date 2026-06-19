"""NestJS pack golden tests (feat-011): controller route extraction, base-path
joining, HANDLED_BY to Class#method, the controller guard, and the negative."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentforge_graph.core import EdgeKind, NodeKind, SourceFile, SymbolID
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack
from agentforge_graph.frameworks.packs.nestjs import NESTJS_PACK

FIXTURES = Path(__file__).parent / "fixtures" / "nestjs"


def _sf(name: str) -> SourceFile:
    raw = (FIXTURES / name).read_bytes()
    return SourceFile(
        path=name, text=raw.decode(), language="ts", content_hash=hashlib.sha256(raw).hexdigest()
    )


def _src(text: str) -> SourceFile:
    return SourceFile(
        path="c.ts",
        text=text,
        language="ts",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def _facts() -> FrameworkFacts:
    return NESTJS_PACK.extract(_sf("users.controller.ts"), repo="fixture", commit="c0")


def test_pack_is_a_framework_pack() -> None:
    assert isinstance(NESTJS_PACK, FrameworkPack)
    assert NESTJS_PACK.name == "nestjs"
    assert NESTJS_PACK.language == "typescript" and NESTJS_PACK.language_slug == "ts"


def test_routes_extracted_with_base_path() -> None:
    facts = _facts()
    routes = {n.name for n in facts.nodes if n.kind is NodeKind.ROUTE}
    assert routes == {
        "GET /users",
        "GET /users/:id",
        "POST /users",
        "DELETE /users/:id",
    }


def test_handled_by_targets_class_method() -> None:
    facts = _facts()
    handled = {(e.src, e.dst) for e in facts.edges if e.kind is EdgeKind.HANDLED_BY}
    one = next(n for n in facts.nodes if n.name == "GET /users/:id")
    assert (one.id, one.attrs["handler"]) in handled
    assert SymbolID.parse(one.attrs["handler"]).descriptor == "UsersController#findOne()."


def test_non_controller_class_is_skipped() -> None:
    facts = _facts()
    handlers = {
        SymbolID.parse(n.attrs["handler"]).descriptor
        for n in facts.nodes
        if n.kind is NodeKind.ROUTE
    }
    assert all("NotAController" not in h for h in handlers)


def test_controller_without_base_path() -> None:
    facts = NESTJS_PACK.extract(
        _src(
            "import { Controller, Get } from '@nestjs/common';\n"
            "@Controller()\n"
            "export class C {\n"
            "  @Get('ping')\n"
            "  ping() { return 1; }\n"
            "}\n"
        ),
        repo="fixture",
        commit="c0",
    )
    route = next(n for n in facts.nodes if n.kind is NodeKind.ROUTE)
    assert route.name == "GET /ping"


def test_no_routes_on_plain_file() -> None:
    facts = NESTJS_PACK.extract(
        _src("export class C { m() { return 1; } }\n"), repo="fixture", commit="c0"
    )
    assert facts.nodes == [] and facts.edges == [] and facts.unresolved == 0
