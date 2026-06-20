"""Laravel pack golden tests (ENH-012): Route::verb DSL, the three handler
shapes, closures, and the dynamic-path counter — on FrameworkFacts."""

from __future__ import annotations

import hashlib

from agentforge_graph.core import NodeKind, SourceFile
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack
from agentforge_graph.frameworks.packs.laravel import LARAVEL_PACK


def _src(body: str) -> SourceFile:
    text = "<?php\nuse Illuminate\\Support\\Facades\\Route;\n" + body
    return SourceFile(
        path="routes/web.php",
        text=text,
        language="php",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def _facts(body: str) -> FrameworkFacts:
    return LARAVEL_PACK.extract(_src(body), repo="fixture", commit="c0")


def test_pack_is_a_framework_pack() -> None:
    assert isinstance(LARAVEL_PACK, FrameworkPack)
    assert LARAVEL_PACK.name == "laravel"
    assert LARAVEL_PACK.language == "php" and LARAVEL_PACK.language_slug == "php"


def test_detect_via_import_marker() -> None:
    assert LARAVEL_PACK.detect(set(), "use Illuminate\\Support\\Facades\\Route;") is True
    assert LARAVEL_PACK.detect(set(), "<?php echo 1;") is False


def test_array_handler_records_controller_and_method() -> None:
    facts = _facts("Route::get('/users', [UserController::class, 'index']);\n")
    route = next(n for n in facts.nodes if n.kind is NodeKind.ROUTE)
    assert route.name == "GET /users"
    assert route.attrs["handler_class"] == "UserController"
    assert route.attrs["handler_method"] == "index"
    assert route.attrs["handler"] == ""  # grounded cross-file by pass-2
    assert route.attrs["path_pattern"] == "/users"


def test_string_handler_at_syntax() -> None:
    facts = _facts("Route::post('/p', 'App\\Http\\Controllers\\PostController@store');\n")
    route = next(n for n in facts.nodes if n.kind is NodeKind.ROUTE)
    assert route.attrs["method"] == "POST"
    assert route.attrs["handler_class"] == "PostController"  # namespace stripped
    assert route.attrs["handler_method"] == "store"


def test_invokable_controller_uses_invoke() -> None:
    facts = _facts("Route::get('/now', ShowClock::class);\n")
    route = next(n for n in facts.nodes if n.kind is NodeKind.ROUTE)
    assert route.attrs["handler_class"] == "ShowClock"
    assert route.attrs["handler_method"] == "__invoke"


def test_closure_handler_has_no_controller_ref() -> None:
    facts = _facts("Route::get('/health', function () { return 'ok'; });\n")
    route = next(n for n in facts.nodes if n.kind is NodeKind.ROUTE)
    assert route.attrs["handler_class"] == "" and route.attrs["handler_method"] == ""


def test_non_route_facade_ignored() -> None:
    facts = _facts("Cache::get('key');\nRoute::middleware('auth');\n")
    # Cache:: is not the Route facade; Route::middleware is not an HTTP verb.
    assert [n for n in facts.nodes if n.kind is NodeKind.ROUTE] == []


def test_dynamic_path_counted() -> None:
    facts = _facts("Route::get($path, [C::class, 'm']);\n")
    assert [n for n in facts.nodes if n.kind is NodeKind.ROUTE] == []
    assert facts.unresolved == 1
